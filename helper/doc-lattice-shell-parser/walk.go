// Package main implements context-carrying shell syntax traversal.
package main

import (
	"sort"
	"strings"

	"mvdan.cc/sh/v3/syntax"
)

type commandSite struct {
	call        *syntax.CallExpr
	argv        []*syntax.Word
	assignments []*syntax.Assign
}

type walker struct {
	src      string
	sites    []commandSite
	refusals []rawRefusal
	work     int
	depth    int
	nodes    int
	events   int
	nodeCap  int
	depthCap int
	eventCap int
	stop     bool
}

func walk(stmts []*syntax.Stmt, src string) (sites []commandSite, refusals []rawRefusal, work int) {
	w := newWalker(src)
	for _, stmt := range stmts {
		w.dispatch(stmt, "command-and-redirects", 1)
		if w.stop {
			break
		}
	}
	return w.sites, w.refusals, w.work
}

func newWalker(src string) *walker {
	return &walker{
		src:      src,
		nodeCap:  visitorNodeCap,
		depthCap: visitorDepthCap,
		eventCap: eventCap,
	}
}

func (w *walker) dispatch(node syntax.Node, role string, depth int) {
	if node == nil || w.stop {
		return
	}
	name, known := syntaxNodeName(node)
	if known && name == "" {
		return
	}
	if !w.visit(node, depth) {
		return
	}
	if !known {
		w.emitCheckedTerminalRefusal(node, "unsupported-construct")
		return
	}
	disposition, ok := certifiedConstructs[constructKey{node: name, role: role}]
	if !ok {
		disposition, ok = certifiedConstructs[constructKey{node: name, role: "*"}]
	}
	if !ok {
		w.emitCheckedTerminalRefusal(node, "unsupported-construct")
		return
	}
	switch disposition {
	case "traverse":
		w.traverse(node, role, depth)
	case "ignore":
		return
	default:
		w.emitRefusal(node, "unsupported-construct")
	}
}

func (w *walker) traverse(node syntax.Node, role string, depth int) {
	switch node := node.(type) {
	case *syntax.Stmt:
		w.walkStmt(node, depth)
	case *syntax.CallExpr:
		w.emitSite(node)
		for _, assign := range node.Assigns {
			w.dispatch(assign, "value", depth+1)
		}
		for _, arg := range node.Args {
			w.consumeWord(arg, depth+1)
		}
	case *syntax.Assign:
		w.walkAssign(node, depth)
	case *syntax.Redirect:
		w.walkRedirect(node, role, depth)
	case *syntax.BinaryCmd:
		w.dispatch(node.X, "command-and-redirects", depth+1)
		w.dispatch(node.Y, "command-and-redirects", depth+1)
	case *syntax.Block:
		w.walkStatements(node.Stmts, depth+1)
	case *syntax.Subshell:
		w.walkStatements(node.Stmts, depth+1)
	case *syntax.CmdSubst:
		w.walkStatements(node.Stmts, depth+1)
	case *syntax.FuncDecl:
		w.dispatch(node.Body, "command-and-redirects", depth+1)
	case *syntax.IfClause:
		w.walkStatements(node.Cond, depth+1)
		w.walkStatements(node.Then, depth+1)
		w.dispatch(node.Else, "condition-and-body", depth+1)
	case *syntax.WhileClause:
		w.walkStatements(node.Cond, depth+1)
		w.walkStatements(node.Do, depth+1)
	case *syntax.ForClause:
		if node.Loop != nil {
			loopRole := "loop-selector"
			if _, ok := node.Loop.(*syntax.WordIter); ok {
				loopRole = "loop-items"
			}
			w.dispatch(node.Loop, loopRole, depth+1)
		}
		w.walkStatements(node.Do, depth+1)
	case *syntax.WordIter:
		for _, item := range node.Items {
			w.consumeWord(item, depth+1)
		}
	case *syntax.CaseClause:
		w.consumeWord(node.Word, depth+1)
		for _, item := range node.Items {
			w.dispatch(item, "patterns-and-body", depth+1)
		}
	case *syntax.CaseItem:
		for _, pattern := range node.Patterns {
			w.consumeWord(pattern, depth+1)
		}
		w.walkStatements(node.Stmts, depth+1)
	default:
		w.emitRefusal(node, "unsupported-construct")
	}
}

func (w *walker) walkStmt(stmt *syntax.Stmt, depth int) {
	type child struct {
		node  syntax.Node
		role  string
		start uint
	}
	children := make([]child, 0, len(stmt.Redirs)+1)
	if stmt.Cmd != nil && !syntaxNodeIsNil(stmt.Cmd) {
		children = append(children, child{node: stmt.Cmd, role: commandRole(stmt.Cmd), start: stmt.Cmd.Pos().Offset()})
	}
	for _, redirect := range stmt.Redirs {
		if redirect != nil {
			children = append(children, child{node: redirect, role: redirectRole(redirect), start: redirect.Pos().Offset()})
		}
	}
	sort.SliceStable(children, func(i, j int) bool { return children[i].start < children[j].start })
	for _, child := range children {
		w.dispatch(child.node, child.role, depth+1)
		if w.stop {
			return
		}
	}
}

func (w *walker) walkStatements(stmts []*syntax.Stmt, depth int) {
	for _, stmt := range stmts {
		w.dispatch(stmt, "command-and-redirects", depth)
		if w.stop {
			return
		}
	}

}

func (w *walker) walkAssign(assign *syntax.Assign, depth int) {
	if assign.Index != nil {
		w.dispatch(assign.Index, "assignment-index", depth+1)
	}
	if assign.Array != nil {
		w.dispatch(assign.Array, "assignment-array", depth+1)
	}
	if assign.Value != nil {
		w.consumeWord(assign.Value, depth+1)
	}
}

func (w *walker) walkRedirect(redirect *syntax.Redirect, role string, depth int) {
	switch role {
	case "target-word-expansion":
		w.consumeWord(redirect.Word, depth+1)
	case "unquoted-heredoc-body":
		w.consumeWord(redirect.Hdoc, depth+1)
	}
}

func (w *walker) consumeWord(word *syntax.Word, depth int) {
	if word == nil || w.stop || !w.visit(word, depth) {
		return
	}
	for _, part := range word.Parts {
		w.consumeWordPart(part, depth+1)
		if w.stop {
			return
		}
	}
}

func (w *walker) consumeWordPart(part syntax.WordPart, depth int) {
	if part == nil || w.stop || syntaxNodeIsNil(part) {
		return
	}
	switch part := part.(type) {
	case *syntax.Lit, *syntax.SglQuoted:
		w.visit(part, depth)
	case *syntax.DblQuoted:
		if !w.visit(part, depth) {
			return
		}
		for _, nested := range part.Parts {
			w.consumeWordPart(nested, depth+1)
			if w.stop {
				return
			}
		}
	case *syntax.CmdSubst:
		w.dispatch(part, "body-statements", depth)
	default:
		w.dispatch(part, "word-part", depth)
	}
}

func (w *walker) visit(node syntax.Node, depth int) bool {
	if w.stop {
		return false
	}
	w.work++
	w.nodes++
	w.depth = max(w.depth, depth)
	if w.nodes > w.nodeCap {
		w.emitTerminalRefusal(node, "work-cap")
		return false
	}
	if depth > w.depthCap {
		w.emitTerminalRefusal(node, "depth-cap")
		return false
	}
	return true
}

func (w *walker) emitSite(call *syntax.CallExpr) {
	if w.stop {
		return
	}
	if w.events >= w.eventCap {
		w.emitTerminalRefusal(call, "event-cap")
		return
	}
	w.sites = append(w.sites, commandSite{
		call:        call,
		argv:        call.Args,
		assignments: call.Assigns,
	})
	w.events++
	w.work++
}

func (w *walker) emitRefusal(node syntax.Node, code string) {
	if w.stop {
		return
	}
	if w.events >= w.eventCap {
		w.emitTerminalRefusal(node, "event-cap")
		return
	}
	start, end := w.nodeSpan(node)
	w.refusals = append(w.refusals, rawRefusal{code: code, startByte: start, endByte: end})
	w.events++
	w.work++
}

func (w *walker) emitTerminalRefusal(node syntax.Node, code string) {
	if w.stop {
		return
	}
	start, end := w.nodeSpan(node)
	w.refusals = append(w.refusals, rawRefusal{code: code, startByte: start, endByte: end})
	w.events++
	w.work++
	w.stop = true
}

func (w *walker) emitCheckedTerminalRefusal(node syntax.Node, code string) {
	if w.stop {
		return
	}
	if w.events >= w.eventCap {
		w.emitTerminalRefusal(node, "event-cap")
		return
	}
	w.emitTerminalRefusal(node, code)
}

func (w *walker) nodeSpan(node syntax.Node) (int, int) {
	start, end := 0, 0
	if pos := node.Pos(); pos.IsValid() {
		start = int(pos.Offset())
	}
	if pos := node.End(); pos.IsValid() {
		end = int(pos.Offset())
	}
	start = min(max(start, 0), len(w.src))
	end = min(max(end, start), len(w.src))
	return start, end
}

func commandRole(command syntax.Command) string {
	switch command.(type) {
	case *syntax.CallExpr:
		return "argv"
	case *syntax.BinaryCmd:
		return "operand-statements"
	case *syntax.Block, *syntax.Subshell:
		return "body-statements"
	case *syntax.FuncDecl:
		return "body"
	case *syntax.IfClause, *syntax.WhileClause:
		return "condition-and-body"
	case *syntax.ForClause:
		return "loop-body-and-selector"
	case *syntax.CaseClause:
		return "selector-word"
	default:
		return "command"
	}
}

func redirectRole(redirect *syntax.Redirect) string {
	if redirect.Op != syntax.Hdoc && redirect.Op != syntax.DashHdoc {
		return "target-word-expansion"
	}
	if heredocDelimiterQuoted(redirect.Word) {
		return "quoted-heredoc-body"
	}
	return "unquoted-heredoc-body"
}

func heredocDelimiterQuoted(word *syntax.Word) bool {
	if word == nil {
		return false
	}
	for _, part := range word.Parts {
		if part == nil || syntaxNodeIsNil(part) {
			continue
		}
		switch part := part.(type) {
		case *syntax.Lit:
			if strings.Contains(part.Value, `\`) {
				return true
			}
		case *syntax.SglQuoted, *syntax.DblQuoted:
			return true
		default:
			return true
		}
	}
	return false
}

func syntaxNodeName(node syntax.Node) (string, bool) {
	switch node := node.(type) {
	case *syntax.File:
		return knownNodeName(node, "File")
	case *syntax.Comment:
		return knownNodeName(node, "Comment")
	case *syntax.Stmt:
		return knownNodeName(node, "Stmt")
	case *syntax.Assign:
		return knownNodeName(node, "Assign")
	case *syntax.Redirect:
		return knownNodeName(node, "Redirect")
	case *syntax.CallExpr:
		return knownNodeName(node, "CallExpr")
	case *syntax.Subshell:
		return knownNodeName(node, "Subshell")
	case *syntax.Block:
		return knownNodeName(node, "Block")
	case *syntax.IfClause:
		return knownNodeName(node, "IfClause")
	case *syntax.WhileClause:
		return knownNodeName(node, "WhileClause")
	case *syntax.ForClause:
		return knownNodeName(node, "ForClause")
	case *syntax.WordIter:
		return knownNodeName(node, "WordIter")
	case *syntax.CStyleLoop:
		return knownNodeName(node, "CStyleLoop")
	case *syntax.BinaryCmd:
		return knownNodeName(node, "BinaryCmd")
	case *syntax.FuncDecl:
		return knownNodeName(node, "FuncDecl")
	case *syntax.Word:
		return knownNodeName(node, "Word")
	case *syntax.Lit:
		return knownNodeName(node, "Lit")
	case *syntax.SglQuoted:
		return knownNodeName(node, "SglQuoted")
	case *syntax.DblQuoted:
		return knownNodeName(node, "DblQuoted")
	case *syntax.CmdSubst:
		return knownNodeName(node, "CmdSubst")
	case *syntax.ParamExp:
		return knownNodeName(node, "ParamExp")
	case *syntax.ArithmExp:
		return knownNodeName(node, "ArithmExp")
	case *syntax.ArithmCmd:
		return knownNodeName(node, "ArithmCmd")
	case *syntax.BinaryArithm:
		return knownNodeName(node, "BinaryArithm")
	case *syntax.UnaryArithm:
		return knownNodeName(node, "UnaryArithm")
	case *syntax.ParenArithm:
		return knownNodeName(node, "ParenArithm")
	case *syntax.FlagsArithm:
		return knownNodeName(node, "FlagsArithm")
	case *syntax.CaseClause:
		return knownNodeName(node, "CaseClause")
	case *syntax.CaseItem:
		return knownNodeName(node, "CaseItem")
	case *syntax.TestClause:
		return knownNodeName(node, "TestClause")
	case *syntax.BinaryTest:
		return knownNodeName(node, "BinaryTest")
	case *syntax.UnaryTest:
		return knownNodeName(node, "UnaryTest")
	case *syntax.ParenTest:
		return knownNodeName(node, "ParenTest")
	case *syntax.DeclClause:
		return knownNodeName(node, "DeclClause")
	case *syntax.ArrayExpr:
		return knownNodeName(node, "ArrayExpr")
	case *syntax.ArrayElem:
		return knownNodeName(node, "ArrayElem")
	case *syntax.ExtGlob:
		return knownNodeName(node, "ExtGlob")
	case *syntax.ProcSubst:
		return knownNodeName(node, "ProcSubst")
	case *syntax.TimeClause:
		return knownNodeName(node, "TimeClause")
	case *syntax.CoprocClause:
		return knownNodeName(node, "CoprocClause")
	case *syntax.LetClause:
		return knownNodeName(node, "LetClause")
	case *syntax.BraceExp:
		return knownNodeName(node, "BraceExp")
	case *syntax.TestDecl:
		return knownNodeName(node, "TestDecl")
	default:
		return "", false
	}
}

func syntaxNodeIsNil(node syntax.Node) bool {
	name, known := syntaxNodeName(node)
	return known && name == ""
}

func knownNodeName[T any](node *T, name string) (string, bool) {
	if node == nil {
		return "", true
	}
	return name, true
}
