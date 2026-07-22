// Package main tests context-carrying shell syntax traversal.
package main

import (
	"testing"

	"mvdan.cc/sh/v3/syntax"
)

func TestWalkCertifiesSimpleCommand(t *testing.T) {
	const src = `doc-lattice check`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}

	sites, refusals, _ := walk(stmts, src)
	if len(sites) != 1 || len(refusals) != 0 {
		t.Fatalf("walk returned %d sites and %d refusals, want 1 and 0", len(sites), len(refusals))
	}
	if len(sites[0].argv) != 2 {
		t.Fatalf("walk site argv length = %d, want 2", len(sites[0].argv))
	}
}

func TestWalkRefusesUnmodeledConstruct(t *testing.T) {
	const src = `cat <(doc-lattice check)`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}

	_, refusals, _ := walk(stmts, src)
	if len(refusals) == 0 {
		t.Fatal("walk returned no refusals, want a ProcSubst refusal")
	}
}

func TestWalkTraversesCommandSubstInArgv(t *testing.T) {
	const src = `echo "$(doc-lattice lint)"`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}

	sites, refusals, _ := walk(stmts, src)
	if len(refusals) != 0 || len(sites) != 2 {
		t.Fatalf("walk returned %d sites and %d refusals, want 2 and 0", len(sites), len(refusals))
	}
}

func TestWalkTraversesCommandSubstInAssignmentValue(t *testing.T) {
	const src = `value=$(doc-lattice check) echo ok`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}

	sites, refusals, _ := walk(stmts, src)
	if len(refusals) != 0 || len(sites) != 2 {
		t.Fatalf("walk returned %d sites and %d refusals, want 2 and 0", len(sites), len(refusals))
	}
}

func TestWalkTraversesCompoundStatements(t *testing.T) {
	tests := []struct {
		name      string
		src       string
		wantSites int
	}{
		{name: "binary block and subshell", src: `{ echo left; } && (echo right)`, wantSites: 2},
		{name: "if else", src: `if echo cond; then echo yes; else echo no; fi`, wantSites: 3},
		{name: "while", src: `while echo cond; do echo body; done`, wantSites: 2},
		{name: "function", src: `f() { echo body; }`, wantSites: 1},
		{name: "for word", src: `for x in "$(echo item)"; do echo body; done`, wantSites: 2},
		{name: "case", src: `case "$(echo selector)" in x) echo body;; esac`, wantSites: 2},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			stmts, refusal := parseStatements(test.src)
			if refusal != nil {
				t.Fatalf("parseStatements refusal = %#v, want none", refusal)
			}
			sites, refusals, _ := walk(stmts, test.src)
			if len(sites) != test.wantSites || len(refusals) != 0 {
				t.Fatalf("walk returned %d sites and %d refusals, want %d and 0", len(sites), len(refusals), test.wantSites)
			}
		})
	}
}

func TestWalkTraversesRedirectExpansions(t *testing.T) {
	tests := []struct {
		name      string
		src       string
		wantSites int
	}{
		{name: "target", src: `echo outer >"$(echo target)"`, wantSites: 2},
		{name: "unquoted heredoc", src: "cat <<EOF\n$(echo body)\nEOF\n", wantSites: 2},
		{name: "quoted heredoc", src: "cat <<'EOF'\n$(echo inert)\nEOF\n", wantSites: 1},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			stmts, refusal := parseStatements(test.src)
			if refusal != nil {
				t.Fatalf("parseStatements refusal = %#v, want none", refusal)
			}
			sites, refusals, _ := walk(stmts, test.src)
			if len(sites) != test.wantSites || len(refusals) != 0 {
				t.Fatalf("walk returned %d sites and %d refusals, want %d and 0", len(sites), len(refusals), test.wantSites)
			}
		})
	}
}

func TestWalkOrdersLeadingRedirectBeforeCommand(t *testing.T) {
	const src = `>"$(nested)" outer`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	sites, refusals, _ := walk(stmts, src)
	if len(sites) != 2 || len(refusals) != 0 {
		t.Fatalf("walk returned %d sites and %d refusals, want 2 and 0", len(sites), len(refusals))
	}
	if got := sites[0].argv[0].Lit(); got != "nested" {
		t.Fatalf("first site head = %q, want nested", got)
	}
}

func TestWalkTreatsEscapedHeredocDelimiterAsQuoted(t *testing.T) {
	const src = "cat <<\\EOF\n$(echo inert)\nEOF\n"
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	redirect := stmts[0].Redirs[0]
	if role := redirectRole(redirect); role != "quoted-heredoc-body" {
		t.Fatalf("redirectRole = %q, want quoted-heredoc-body", role)
	}
	sites, refusals, _ := walk(stmts, src)
	if len(sites) != 1 || len(refusals) != 0 {
		t.Fatalf("walk returned %d sites and %d refusals, want 1 and 0", len(sites), len(refusals))
	}
}

func TestWalkRefusesAssignmentIndexAndArray(t *testing.T) {
	tests := []struct {
		name   string
		assign *syntax.Assign
	}{
		{
			name: "index",
			assign: &syntax.Assign{Index: &syntax.Word{Parts: []syntax.WordPart{&syntax.Lit{
				ValuePos: syntax.NewPos(0, 1, 1), ValueEnd: syntax.NewPos(1, 1, 2), Value: "0",
			}}}},
		},
		{
			name: "array",
			assign: &syntax.Assign{Array: &syntax.ArrayExpr{
				Lparen: syntax.NewPos(0, 1, 1), Rparen: syntax.NewPos(1, 1, 2),
			}},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			w := newWalker("x")
			w.dispatch(test.assign, "value", 1)
			if len(w.refusals) == 0 || w.refusals[0].code != "unsupported-construct" {
				t.Errorf("assignment refusals = %#v, want unsupported-construct", w.refusals)
			}
		})
	}
}

func TestWalkRefusesWildcardOnlyNodes(t *testing.T) {
	for _, src := range []string{`((1 + 2))`, `echo "$value"`} {
		stmts, refusal := parseStatements(src)
		if refusal != nil {
			t.Fatalf("parseStatements(%q) refusal = %#v, want none", src, refusal)
		}
		_, refusals, _ := walk(stmts, src)
		if len(refusals) == 0 || refusals[0].code != "unsupported-construct" {
			t.Errorf("walk(%q) refusals = %#v, want unsupported-construct", src, refusals)
		}
	}
}

func TestWalkTerminalRefusalSuppressesLaterSiblings(t *testing.T) {
	const src = `((1)); echo after`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	sites, refusals, _ := walk(stmts, src)
	if len(sites) != 0 {
		t.Fatalf("sites = %d, want no site after terminal refusal", len(sites))
	}
	if len(refusals) != 1 || refusals[0].code != "unsupported-construct" {
		t.Fatalf("refusals = %#v, want one unsupported-construct", refusals)
	}
}

func TestWalkTerminalRefusalCapPrecedenceIsSingleEvent(t *testing.T) {
	const src = `((1))`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	command := stmts[0].Cmd
	tests := []struct {
		name      string
		configure func(*walker)
		wantCode  string
	}{
		{
			name:      "work cap replaces unsupported",
			configure: func(w *walker) { w.workLimit = 1 },
			wantCode:  "work-cap",
		},
		{
			name: "event cap wins over work cap",
			configure: func(w *walker) {
				w.workLimit = 1
				w.eventCap = 0
			},
			wantCode: "event-cap",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			w := newWalker(src)
			test.configure(w)
			w.dispatch(command, "command", 1)
			if len(w.refusals) != 1 || w.refusals[0].code != test.wantCode {
				t.Fatalf("refusals = %#v, want one %s", w.refusals, test.wantCode)
			}
			if !w.stop || w.events != 1 || w.work != 2 {
				t.Fatalf("stop, events, work = (%t, %d, %d), want (true, 1, 2)", w.stop, w.events, w.work)
			}
		})
	}
}

func TestWalkDispatchUsesExactRoleBeforeWildcard(t *testing.T) {
	const src = `value=$(echo nested) echo outer`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	call := stmts[0].Cmd.(*syntax.CallExpr)

	exact := newWalker(src)
	exact.dispatch(call.Assigns[0], "value", 1)
	if len(exact.sites) != 1 || len(exact.refusals) != 0 {
		t.Fatalf("exact-role dispatch returned %d sites and %d refusals, want 1 and 0", len(exact.sites), len(exact.refusals))
	}

	wildcard := newWalker(src)
	wildcard.dispatch(call.Assigns[0], "wrong-role", 1)
	if len(wildcard.refusals) != 1 || wildcard.refusals[0].code != "unsupported-construct" {
		t.Fatalf("wrong-role dispatch refusals = %#v, want unsupported-construct", wildcard.refusals)
	}
}

func TestWalkCapsEmitOneTerminalRefusal(t *testing.T) {
	const src = `echo one; echo two`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	tests := []struct {
		name      string
		configure func(*walker)
		wantCode  string
	}{
		{name: "work", configure: func(w *walker) { w.workLimit = 1 }, wantCode: "work-cap"},
		{name: "depth", configure: func(w *walker) { w.depthCap = 1 }, wantCode: "depth-cap"},
		{name: "event", configure: func(w *walker) { w.eventCap = 0 }, wantCode: "event-cap"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			w := newWalker(src)
			test.configure(w)
			w.walkStatements(stmts, 1)
			if len(w.refusals) != 1 || w.refusals[0].code != test.wantCode {
				t.Fatalf("cap refusals = %#v, want one %s", w.refusals, test.wantCode)
			}
			if !w.stop {
				t.Fatal("cap breach did not stop traversal")
			}
			if w.work != w.nodes+w.events {
				t.Fatalf("work = %d, nodes + events = %d", w.work, w.nodes+w.events)
			}
		})
	}
}

func TestWalkWorkCapIncludesEmittedEvents(t *testing.T) {
	lit := &syntax.Lit{
		ValuePos: syntax.NewPos(0, 1, 1),
		ValueEnd: syntax.NewPos(1, 1, 2),
		Value:    "x",
	}
	call := &syntax.CallExpr{Args: []*syntax.Word{{Parts: []syntax.WordPart{lit}}}}
	w := newWalker("x")
	w.workLimit = 1
	w.dispatch(call, "argv", 1)

	if len(w.sites) != 1 {
		t.Fatalf("sites = %d, want the crossing command-site event retained", len(w.sites))
	}
	if len(w.refusals) != 1 || w.refusals[0].code != "work-cap" {
		t.Fatalf("refusals = %#v, want one terminal work-cap", w.refusals)
	}
	if !w.stop {
		t.Fatal("work-cap event did not stop traversal")
	}
	if w.nodes != 1 || w.events != 2 || w.work != 3 {
		t.Fatalf("nodes, events, work = (%d, %d, %d), want (1, 2, 3)", w.nodes, w.events, w.work)
	}
}

func TestWalkUnknownNodeFailsClosedAndClampsSpan(t *testing.T) {
	w := newWalker("abc")
	w.dispatch(unknownWalkNode{}, "anything", 1)
	if len(w.refusals) != 1 || w.refusals[0].code != "unsupported-construct" {
		t.Fatalf("unknown-node refusals = %#v, want unsupported-construct", w.refusals)
	}
	if got := w.refusals[0]; got.startByte != 3 || got.endByte != 3 {
		t.Fatalf("unknown-node span = [%d, %d), want [3, 3)", got.startByte, got.endByte)
	}
	if !w.stop {
		t.Fatal("unknown node did not stop traversal")
	}
}

func TestWalkMalformedNodesFailClosedWithoutPanicking(t *testing.T) {
	dispatch := func(node syntax.Node, role string) func() ([]rawRefusal, bool) {
		return func() ([]rawRefusal, bool) {
			w := newWalker("")
			w.dispatch(node, role, 1)
			return w.refusals, w.stop
		}
	}
	tests := []struct {
		name     string
		wantCode string
		run      func() ([]rawRefusal, bool)
	}{
		{
			name:     "statement source order",
			wantCode: "unsupported-construct",
			run: func() ([]rawRefusal, bool) {
				_, refusals, _ := walk([]*syntax.Stmt{{Cmd: &syntax.CallExpr{}}}, "")
				return refusals, len(refusals) > 0
			},
		},
		{
			name:     "normal dispatch",
			wantCode: "unsupported-construct",
			run:      dispatch(&syntax.Word{}, "word-part"),
		},
		{
			name:     "cap-triggered span",
			wantCode: "work-cap",
			run: func() ([]rawRefusal, bool) {
				w := newWalker("")
				w.workLimit = 0
				w.dispatch(&syntax.Word{}, "word-part", 1)
				return w.refusals, w.stop
			},
		},
		{name: "empty statement", wantCode: "unsupported-construct", run: dispatch(&syntax.Stmt{}, "command-and-redirects")},
		{name: "empty block", wantCode: "unsupported-construct", run: dispatch(&syntax.Block{}, "body-statements")},
		{name: "empty subshell", wantCode: "unsupported-construct", run: dispatch(&syntax.Subshell{}, "body-statements")},
		{name: "empty command substitution", wantCode: "unsupported-construct", run: dispatch(&syntax.CmdSubst{}, "body-statements")},
		{name: "empty if", wantCode: "unsupported-construct", run: dispatch(&syntax.IfClause{}, "condition-and-body")},
		{name: "empty while", wantCode: "unsupported-construct", run: dispatch(&syntax.WhileClause{}, "condition-and-body")},
		{name: "empty for", wantCode: "unsupported-construct", run: dispatch(&syntax.ForClause{}, "loop-body-and-selector")},
		{name: "empty case", wantCode: "unsupported-construct", run: dispatch(&syntax.CaseClause{}, "selector-word")},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			refusals, stopped := test.run()
			if len(refusals) != 1 || refusals[0].code != test.wantCode {
				t.Fatalf("refusals = %#v, want one %s", refusals, test.wantCode)
			}
			if refusals[0].startByte != 0 || refusals[0].endByte != 0 {
				t.Fatalf("span = [%d, %d), want [0, 0)", refusals[0].startByte, refusals[0].endByte)
			}
			if !stopped {
				t.Fatal("malformed node did not stop traversal")
			}
		})
	}
}

func TestWalkEventCapPrecedesUnknownRefusalEmission(t *testing.T) {
	w := newWalker("abc")
	w.eventCap = 0
	w.dispatch(unknownWalkNode{}, "anything", 1)
	if len(w.refusals) != 1 || w.refusals[0].code != "event-cap" {
		t.Fatalf("unknown node at event cap produced %#v, want one event-cap", w.refusals)
	}
}

func TestWalkDoesNotChargeTypedNilChildren(t *testing.T) {
	t.Run("dispatch", func(t *testing.T) {
		w := newWalker("")
		var clause *syntax.IfClause
		w.dispatch(clause, "condition-and-body", 1)
		if w.work != 0 || w.nodes != 0 || len(w.refusals) != 0 {
			t.Fatalf("typed-nil dispatch left work %d, nodes %d, refusals %#v; want all zero", w.work, w.nodes, w.refusals)
		}
	})

	t.Run("statement command makes parent malformed", func(t *testing.T) {
		var call *syntax.CallExpr
		stmt := &syntax.Stmt{Cmd: call}
		_, refusals, work := walk([]*syntax.Stmt{stmt}, "")
		if work != 1 || len(refusals) != 1 || refusals[0].code != "unsupported-construct" {
			t.Fatalf("typed-nil command left work %d and refusals %#v, want 1 and unsupported-construct", work, refusals)
		}
	})

	t.Run("word part makes parent malformed", func(t *testing.T) {
		w := newWalker("")
		var quoted *syntax.DblQuoted
		word := &syntax.Word{Parts: []syntax.WordPart{quoted}}
		w.consumeWord(word, 1)
		if w.work != 1 || w.nodes != 0 || len(w.refusals) != 1 || w.refusals[0].code != "unsupported-construct" {
			t.Fatalf("typed-nil word part left work %d, nodes %d, refusals %#v; want 1, 0, and unsupported-construct", w.work, w.nodes, w.refusals)
		}
	})
}

func TestWalkStopsChildLoopsImmediately(t *testing.T) {
	litWord := func(offset uint, value string) *syntax.Word {
		return &syntax.Word{Parts: []syntax.WordPart{&syntax.Lit{
			ValuePos: syntax.NewPos(offset, 1, offset+1),
			ValueEnd: syntax.NewPos(offset+uint(len(value)), 1, offset+uint(len(value))+1),
			Value:    value,
		}}}
	}
	procWord := func(offset uint) *syntax.Word {
		return &syntax.Word{Parts: []syntax.WordPart{&syntax.ProcSubst{
			OpPos:  syntax.NewPos(offset, 1, offset+1),
			Rparen: syntax.NewPos(offset+2, 1, offset+3),
		}}}
	}

	t.Run("call assignments and args", func(t *testing.T) {
		first := &syntax.Assign{
			Name: &syntax.Lit{ValuePos: syntax.NewPos(0, 1, 1), ValueEnd: syntax.NewPos(1, 1, 2), Value: "x"},
			Array: &syntax.ArrayExpr{
				Lparen: syntax.NewPos(2, 1, 3), Rparen: syntax.NewPos(3, 1, 4),
			},
		}
		second := &syntax.Assign{
			Name:  &syntax.Lit{ValuePos: syntax.NewPos(4, 1, 5), ValueEnd: syntax.NewPos(5, 1, 6), Value: "y"},
			Value: litWord(6, "ok"),
		}
		call := &syntax.CallExpr{Assigns: []*syntax.Assign{first, second}, Args: []*syntax.Word{litWord(9, "later")}}
		w := newWalker("x=() y=ok later")
		w.dispatch(call, "argv", 1)
		if w.childSteps != 1 {
			t.Fatalf("child loop steps = %d, want 1", w.childSteps)
		}
	})

	t.Run("word iterator items", func(t *testing.T) {
		iter := &syntax.WordIter{
			Name:  &syntax.Lit{ValuePos: syntax.NewPos(0, 1, 1), ValueEnd: syntax.NewPos(1, 1, 2), Value: "x"},
			Items: []*syntax.Word{procWord(2), litWord(6, "later")},
		}
		w := newWalker("x <() later")
		w.dispatch(iter, "loop-items", 1)
		if w.childSteps != 2 {
			t.Fatalf("child loop steps = %d, want 2", w.childSteps)
		}
	})

	t.Run("case items and patterns", func(t *testing.T) {
		clause := &syntax.CaseClause{
			Word: litWord(0, "x"),
			Items: []*syntax.CaseItem{
				{Patterns: []*syntax.Word{procWord(2)}},
				{Patterns: []*syntax.Word{litWord(6, "later")}},
			},
		}
		w := newWalker("x <() later")
		w.dispatch(clause, "selector-word", 1)
		if w.childSteps != 4 {
			t.Fatalf("child loop steps = %d, want 4", w.childSteps)
		}
	})
}

func TestWalkStopsBeforeScanningRemainingRedirects(t *testing.T) {
	redirect := func(offset uint) *syntax.Redirect {
		return &syntax.Redirect{
			OpPos: syntax.NewPos(offset, 1, offset+1),
			Word: &syntax.Word{Parts: []syntax.WordPart{&syntax.Lit{
				ValuePos: syntax.NewPos(offset+1, 1, offset+2),
				ValueEnd: syntax.NewPos(offset+2, 1, offset+3),
				Value:    "x",
			}}},
		}
	}
	stmt := &syntax.Stmt{
		Position: syntax.NewPos(0, 1, 1),
		Cmd: &syntax.ArithmCmd{
			Left: syntax.NewPos(0, 1, 1), Right: syntax.NewPos(3, 1, 4),
		},
		Redirs: []*syntax.Redirect{redirect(6), redirect(9), redirect(12)},
	}
	w := newWalker("((1))>x >x >x")
	w.dispatch(stmt, "command-and-redirects", 1)
	if w.childSteps != 1 {
		t.Fatalf("child loop steps = %d, want only the terminal command step", w.childSteps)
	}
	if len(w.refusals) != 1 || w.refusals[0].code != "unsupported-construct" {
		t.Fatalf("refusals = %#v, want one unsupported-construct", w.refusals)
	}
}

func TestWalkWorkIsDeterministic(t *testing.T) {
	const src = `echo "$(doc-lattice lint)"`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	_, _, first := walk(stmts, src)
	_, _, second := walk(stmts, src)
	if first <= 0 || first != second {
		t.Fatalf("walk work = (%d, %d), want equal positive values", first, second)
	}
}

func TestWalkNodeSwitchCoversPinnedASTTypesAndCertifiedTable(t *testing.T) {
	nodes := []syntax.Node{
		&syntax.File{}, &syntax.Comment{}, &syntax.Stmt{}, &syntax.Assign{}, &syntax.Redirect{},
		&syntax.CallExpr{}, &syntax.Subshell{}, &syntax.Block{}, &syntax.IfClause{},
		&syntax.WhileClause{}, &syntax.ForClause{}, &syntax.WordIter{}, &syntax.CStyleLoop{},
		&syntax.BinaryCmd{}, &syntax.FuncDecl{}, &syntax.Word{}, &syntax.Lit{},
		&syntax.SglQuoted{}, &syntax.DblQuoted{}, &syntax.CmdSubst{}, &syntax.ParamExp{},
		&syntax.ArithmExp{}, &syntax.ArithmCmd{}, &syntax.BinaryArithm{}, &syntax.UnaryArithm{},
		&syntax.ParenArithm{}, &syntax.FlagsArithm{}, &syntax.CaseClause{}, &syntax.CaseItem{},
		&syntax.TestClause{}, &syntax.BinaryTest{}, &syntax.UnaryTest{}, &syntax.ParenTest{},
		&syntax.DeclClause{}, &syntax.ArrayExpr{}, &syntax.ArrayElem{}, &syntax.ExtGlob{},
		&syntax.ProcSubst{}, &syntax.TimeClause{}, &syntax.CoprocClause{}, &syntax.LetClause{},
		&syntax.BraceExp{}, &syntax.TestDecl{},
	}
	for _, node := range nodes {
		name, known := syntaxNodeName(node)
		if !known || name == "" {
			t.Fatalf("syntaxNodeName(%T) = (%q, %t), want a known name", node, name, known)
		}
		hasRow := false
		for key := range certifiedConstructs {
			if key.node == name {
				hasRow = true
				break
			}
		}
		if !hasRow {
			t.Errorf("syntax node %s has no certified construct row", name)
		}
	}

	certifiedNames := make(map[string]struct{})
	for key := range certifiedConstructs {
		certifiedNames[key.node] = struct{}{}
	}
	if len(certifiedNames) != certifiedNodeTypeCount {
		t.Fatalf("certified table covers %d node names, want certifiedNodeTypeCount %d", len(certifiedNames), certifiedNodeTypeCount)
	}
}

func TestWalkDispatchTraversesFileRow(t *testing.T) {
	const src = `doc-lattice check`
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", refusal)
	}
	w := newWalker(src)
	w.dispatch(&syntax.File{Stmts: stmts}, "top-level-statements", 1)
	if len(w.sites) != 1 || len(w.refusals) != 0 {
		t.Fatalf("File dispatch returned %d sites and %d refusals, want 1 and 0", len(w.sites), len(w.refusals))
	}
}

type unknownWalkNode struct{}

func (unknownWalkNode) Pos() syntax.Pos { return syntax.NewPos(99, 1, 100) }
func (unknownWalkNode) End() syntax.Pos { return syntax.NewPos(2, 1, 3) }
