// Package main implements context-carrying shell syntax traversal.
package main

import (
	"strings"

	"mvdan.cc/sh/v3/syntax"
)

type commandSite struct {
	call        *syntax.CallExpr
	argv        []*syntax.Word
	assignments []*syntax.Assign
}

type walker struct {
	src        string
	sites      []commandSite
	refusals   []rawRefusal
	work       int
	depth      int
	nodes      int
	events     int
	childSteps int
	workLimit  int
	depthCap   int
	eventCap   int
	stop       bool
}

func walk(stmts []*syntax.Stmt, src string) (sites []commandSite, refusals []rawRefusal, work int) {
	w := newWalker(src)
	for _, stmt := range stmts {
		if !w.enterChild() {
			break
		}
		w.dispatch(stmt, "command-and-redirects", 1)
		if w.stop {
			break
		}
	}
	return w.sites, w.refusals, w.work
}

func newWalker(src string) *walker {
	return &walker{
		src:       src,
		workLimit: visitorNodeCap,
		depthCap:  visitorDepthCap,
		eventCap:  eventCap,
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
	if _, _, safe := w.safeNodeSpan(node); !safe {
		w.emitMalformedRefusal()
		return
	}
	if !w.visit(node, depth) {
		return
	}
	if !known {
		w.emitTerminalCandidate(node, "unsupported-construct")
		return
	}
	disposition, ok := certifiedConstructs[constructKey{node: name, role: role}]
	if !ok {
		disposition, ok = certifiedConstructs[constructKey{node: name, role: "*"}]
	}
	if !ok {
		w.emitTerminalCandidate(node, "unsupported-construct")
		return
	}
	switch disposition {
	case "traverse":
		w.traverse(node, role, depth)
	case "ignore":
		return
	case "refuse":
		w.emitTerminalCandidate(node, "unsupported-construct")
	default:
		w.emitTerminalCandidate(node, "unsupported-construct")
	}
}

func (w *walker) traverse(node syntax.Node, role string, depth int) {
	switch node := node.(type) {
	case *syntax.File:
		w.walkStatements(node.Stmts, depth+1)
	case *syntax.Stmt:
		w.walkStmt(node, depth)
	case *syntax.CallExpr:
		w.emitSite(node)
		if w.stop {
			return
		}
		for _, assign := range node.Assigns {
			if !w.enterChild() {
				return
			}
			w.dispatch(assign, "value", depth+1)
			if w.stop {
				return
			}
		}
		for _, arg := range node.Args {
			if !w.enterChild() {
				return
			}
			w.consumeWord(arg, depth+1)
			if w.stop {
				return
			}
		}
	case *syntax.Assign:
		w.walkAssign(node, depth)
	case *syntax.Redirect:
		w.walkRedirect(node, role, depth)
	case *syntax.BinaryCmd:
		w.dispatch(node.X, "command-and-redirects", depth+1)
		if w.stop {
			return
		}
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
		if w.stop {
			return
		}
		w.walkStatements(node.Then, depth+1)
		if w.stop {
			return
		}
		w.dispatch(node.Else, "condition-and-body", depth+1)
	case *syntax.WhileClause:
		w.walkStatements(node.Cond, depth+1)
		if w.stop {
			return
		}
		w.walkStatements(node.Do, depth+1)
	case *syntax.ForClause:
		if node.Loop != nil {
			loopRole := "loop-selector"
			if _, ok := node.Loop.(*syntax.WordIter); ok {
				loopRole = "loop-items"
			}
			w.dispatch(node.Loop, loopRole, depth+1)
			if w.stop {
				return
			}
		}
		w.walkStatements(node.Do, depth+1)
	case *syntax.WordIter:
		for _, item := range node.Items {
			if !w.enterChild() {
				return
			}
			w.consumeWord(item, depth+1)
			if w.stop {
				return
			}
		}
	case *syntax.CaseClause:
		w.consumeWord(node.Word, depth+1)
		if w.stop {
			return
		}
		for _, item := range node.Items {
			if !w.enterChild() {
				return
			}
			w.dispatch(item, "patterns-and-body", depth+1)
			if w.stop {
				return
			}
		}
	case *syntax.CaseItem:
		for _, pattern := range node.Patterns {
			if !w.enterChild() {
				return
			}
			w.consumeWord(pattern, depth+1)
			if w.stop {
				return
			}
		}
		w.walkStatements(node.Stmts, depth+1)
	default:
		w.emitTerminalCandidate(node, "unsupported-construct")
	}
}

func (w *walker) walkStmt(stmt *syntax.Stmt, depth int) {
	var command syntax.Command
	commandStart := 0
	if stmt.Cmd != nil && !syntaxNodeIsNil(stmt.Cmd) {
		start, _, safe := w.safeNodeSpan(stmt.Cmd)
		if !safe {
			w.emitMalformedRefusal()
			return
		}
		command = stmt.Cmd
		commandStart = start
	}
	commandWalked := command == nil
	for _, redirect := range stmt.Redirs {
		if redirect == nil {
			continue
		}
		redirectStart, _, safe := w.safeNodeSpan(redirect)
		if !safe {
			w.emitMalformedRefusal()
			return
		}
		if !commandWalked && commandStart <= redirectStart {
			if !w.enterChild() {
				return
			}
			w.dispatch(command, commandRole(command), depth+1)
			commandWalked = true
			if w.stop {
				return
			}
		}
		if !w.enterChild() {
			return
		}
		w.dispatch(redirect, redirectRole(redirect), depth+1)
		if w.stop {
			return
		}
	}
	if !commandWalked && w.enterChild() {
		w.dispatch(command, commandRole(command), depth+1)
	}
}

func (w *walker) walkStatements(stmts []*syntax.Stmt, depth int) {
	for _, stmt := range stmts {
		if !w.enterChild() {
			return
		}
		w.dispatch(stmt, "command-and-redirects", depth)
		if w.stop {
			return
		}
	}

}

func (w *walker) walkAssign(assign *syntax.Assign, depth int) {
	if assign.Index != nil {
		w.dispatch(assign.Index, "assignment-index", depth+1)
		if w.stop {
			return
		}
	}
	if assign.Array != nil {
		w.dispatch(assign.Array, "assignment-array", depth+1)
		if w.stop {
			return
		}
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
	if word == nil || w.stop {
		return
	}
	if _, _, safe := w.safeNodeSpan(word); !safe {
		w.emitMalformedRefusal()
		return
	}
	if !w.visit(word, depth) {
		return
	}
	for _, part := range word.Parts {
		if !w.enterChild() {
			return
		}
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
			if !w.enterChild() {
				return
			}
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

func (w *walker) enterChild() bool {
	if w.stop {
		return false
	}
	w.childSteps++
	return true
}

func (w *walker) visit(node syntax.Node, depth int) bool {
	if w.stop {
		return false
	}
	w.work++
	w.nodes++
	w.depth = max(w.depth, depth)
	if w.work > w.workLimit {
		w.emitCapRefusal(node, "work-cap")
		return false
	}
	if depth > w.depthCap {
		w.emitCapRefusal(node, "depth-cap")
		return false
	}
	return true
}

func (w *walker) emitSite(call *syntax.CallExpr) {
	if w.stop {
		return
	}
	if w.events >= w.eventCap {
		w.emitCapRefusal(call, "event-cap")
		return
	}
	w.sites = append(w.sites, commandSite{
		call:        call,
		argv:        call.Args,
		assignments: call.Assigns,
	})
	w.chargeEvent(call)
}

func (w *walker) chargeEvent(node syntax.Node) {
	w.events++
	w.work++
	if w.work > w.workLimit {
		w.emitCapRefusal(node, "work-cap")
	}
}

func (w *walker) emitTerminalCandidate(node syntax.Node, code string) {
	start, end := w.nodeSpan(node)
	w.emitTerminalAt(start, end, code)
}

func (w *walker) emitTerminalAt(start, end int, code string) {
	if w.stop {
		return
	}
	if w.events >= w.eventCap {
		code = "event-cap"
	} else if w.work+1 > w.workLimit {
		code = "work-cap"
	}
	w.appendTerminalRefusal(start, end, code)
}

func (w *walker) emitCapRefusal(node syntax.Node, code string) {
	start, end := w.nodeSpan(node)
	w.appendTerminalRefusal(start, end, code)
}

func (w *walker) appendTerminalRefusal(start, end int, code string) {
	if w.stop {
		return
	}
	// The chosen terminal refusal is the final charged event and is not recursively cap-checked.
	w.refusals = append(w.refusals, rawRefusal{code: code, startByte: start, endByte: end})
	w.events++
	w.work++
	w.stop = true
}

func (w *walker) emitMalformedRefusal() {
	w.emitTerminalAt(0, 0, "unsupported-construct")
}

func (w *walker) nodeSpan(node syntax.Node) (int, int) {
	start, end, _ := w.safeNodeSpan(node)
	return start, end
}

func (w *walker) safeNodeSpan(node syntax.Node) (start, end int, safe bool) {
	if !nodeStructureValid(node) {
		return 0, 0, false
	}
	defer func() {
		if recover() != nil {
			start, end, safe = 0, 0, false
		}
	}()

	start, end = 0, 0
	if pos := node.Pos(); pos.IsValid() {
		start = int(pos.Offset())
	}
	if pos := node.End(); pos.IsValid() {
		end = int(pos.Offset())
	}
	start = min(max(start, 0), len(w.src))
	end = min(max(end, start), len(w.src))
	return start, end, true
}

func nodeStructureValid(node syntax.Node) bool {
	switch node := node.(type) {
	case *syntax.Stmt:
		return (node.Cmd != nil && !syntaxNodeIsNil(node.Cmd)) || len(node.Redirs) > 0
	case *syntax.CallExpr:
		return len(node.Assigns) > 0 || len(node.Args) > 0
	case *syntax.Redirect:
		return node.Word != nil
	case *syntax.BinaryCmd:
		return node.X != nil && node.Y != nil
	case *syntax.Block:
		return len(node.Stmts) > 0
	case *syntax.Subshell:
		return len(node.Stmts) > 0
	case *syntax.CmdSubst:
		return len(node.Stmts) > 0 || len(node.Last) > 0
	case *syntax.FuncDecl:
		return node.Body != nil
	case *syntax.IfClause:
		return len(node.Cond) > 0 || len(node.Then) > 0 || node.Else != nil
	case *syntax.WhileClause:
		return len(node.Cond) > 0 && len(node.Do) > 0
	case *syntax.ForClause:
		return node.Loop != nil && !syntaxNodeIsNil(node.Loop) && len(node.Do) > 0
	case *syntax.WordIter:
		return node.Name != nil
	case *syntax.CaseClause:
		return node.Word != nil
	case *syntax.CaseItem:
		return len(node.Patterns) > 0
	case *syntax.Word:
		return len(node.Parts) > 0
	default:
		return true
	}
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
