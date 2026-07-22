// Package main contains AST-anchored raw-source divergence guards.
package main

import (
	"sort"
	"strings"

	"mvdan.cc/sh/v3/syntax"
)

type guardFrame struct {
	node  syntax.Node
	depth int
	next  int
}

type guardSpan struct {
	start int
	end   int
}

// heredocGuard rejects backslash-newline continuations only within raw source
// spans confirmed by the parsed AST as heredoc delimiters or active bodies.
func heredocGuard(src string, stmts []*syntax.Stmt) *rawRefusal {
	refusal, _ := scanHeredocGuard(src, stmts)
	return refusal
}

func scanHeredocGuard(src string, stmts []*syntax.Stmt) (*rawRefusal, int) {
	// Raw text may prove that no guard hit is possible, but it can never prove
	// heredoc context; only the AST-projected spans below may cause a refusal.
	if !strings.Contains(src, "\\\n") {
		return nil, 0
	}
	spans, work, ok := heredocGuardSpans(src, stmts)
	if !ok {
		return nil, work
	}
	if offset, ok := firstGuardedContinuation(src, spans); ok {
		if work+1 > visitorNodeCap {
			return nil, work
		}
		return &rawRefusal{
			code:      "parser-divergence-guard",
			startByte: offset,
			endByte:   offset + 2,
		}, work
	}
	return nil, work
}

func heredocGuardSpans(src string, stmts []*syntax.Stmt) ([]guardSpan, int, bool) {
	spans := make([]guardSpan, 0)
	seen := make(map[syntax.Node]struct{})
	nodes := 0
	for _, stmt := range stmts {
		stack := []guardFrame{{node: stmt, depth: 1, next: -1}}
		for len(stack) > 0 {
			frame := &stack[len(stack)-1]
			if frame.next < 0 {
				name, known := syntaxNodeName(frame.node)
				if !known || name == "" || frame.depth > visitorDepthCap || nodes >= visitorNodeCap {
					return nil, nodes, false
				}
				if _, duplicate := seen[frame.node]; duplicate {
					return nil, nodes, false
				}
				seen[frame.node] = struct{}{}
				nodes++
				if !localStructureValid(frame.node) {
					return nil, nodes, false
				}
				if redirect, ok := frame.node.(*syntax.Redirect); ok &&
					(redirect.Op == syntax.Hdoc || redirect.Op == syntax.DashHdoc) {
					delimiterSpan, valid := guardedNodeSpan(redirect.Word, len(src))
					if !valid {
						return nil, nodes, false
					}
					spans = append(spans, delimiterSpan)
					if redirect.Hdoc != nil && !heredocDelimiterQuoted(redirect.Word) {
						span, valid := guardedNodeSpan(redirect.Hdoc, len(src))
						if !valid {
							return nil, nodes, false
						}
						spans = append(spans, span)
					}
				}
				frame.next = 0
			}
			child, ok := nextStructuralChild(frame.node, &frame.next)
			if !ok {
				stack = stack[:len(stack)-1]
				continue
			}
			if child == nil || syntaxNodeIsNil(child) {
				return nil, nodes, false
			}
			stack = append(stack, guardFrame{node: child, depth: frame.depth + 1, next: -1})
		}
	}
	return spans, nodes, true
}

func guardedNodeSpan(node syntax.Node, srcLen int) (guardSpan, bool) {
	start, startOK := boundedStart(node, visitorDepthCap+1)
	end, endOK := boundedEnd(node, visitorDepthCap+1)
	if !startOK || !endOK || validateRawSpan(start, end, srcLen) != nil {
		return guardSpan{}, false
	}
	return guardSpan{start: start, end: end}, true
}

func firstGuardedContinuation(src string, spans []guardSpan) (int, bool) {
	sort.Slice(spans, func(left, right int) bool {
		if spans[left].start != spans[right].start {
			return spans[left].start < spans[right].start
		}
		return spans[left].end < spans[right].end
	})
	scannedThrough := 0
	for _, span := range spans {
		start := max(span.start, scannedThrough)
		if start < span.end {
			if relative := strings.Index(src[start:span.end], "\\\n"); relative >= 0 {
				return start + relative, true
			}
		}
		scannedThrough = max(scannedThrough, span.end)
	}
	return 0, false
}
