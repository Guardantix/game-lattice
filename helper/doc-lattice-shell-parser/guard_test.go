package main

import (
	"reflect"
	"strings"
	"testing"

	"mvdan.cc/sh/v3/syntax"
)

func mustParse(t *testing.T, src string) []*syntax.Stmt {
	t.Helper()
	stmts, refusal := parseStatements(src)
	if refusal != nil {
		t.Fatalf("parseStatements(%q) refusal = %+v", src, refusal)
	}
	return stmts
}

func TestHeredocGuardCatchesBackslashNewline(t *testing.T) {
	const src = "cat <<EOF\n$\\\n(doc-lattice linear)\nEOF\n"
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	result := resp.Results[0]
	if len(result.Events) != 1 {
		t.Fatalf("events = %+v, want only the terminal guard refusal", result.Events)
	}
	event := result.Events[0]
	wantStart := strings.Index(src, "\\\n")
	if event.Kind != "refusal" || event.Code != "parser-divergence-guard" ||
		event.StartByte != wantStart || event.EndByte != wantStart+2 {
		t.Fatalf("guard event = %+v, want parser-divergence-guard at [%d, %d)", event, wantStart, wantStart+2)
	}
	if result.WorkUnits != 12 {
		t.Fatalf("work_units = %d, want 10 visited nodes plus refusal and source base = 12", result.WorkUnits)
	}
}

func TestHeredocGuardAllowsQuotedDelimiter(t *testing.T) {
	const src = "cat <<'EOF'\n$\\\n(doc-lattice linear)\nEOF\n"
	if got := heredocGuard(src, mustParse(t, src)); got != nil {
		t.Fatalf("quoted-delimiter heredoc must not trip the guard, got %+v", got)
	}
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	if got := refusalCodes(resp.Results[0].Events); len(got) != 0 {
		t.Fatalf("quoted-delimiter heredoc refusals = %#v, want none", got)
	}
	if got := commandHeads(t, resp.Results[0].Events); !reflect.DeepEqual(got, []string{"cat"}) {
		t.Fatalf("quoted-delimiter command heads = %#v, want only cat", got)
	}
}

func TestHeredocGuardCatchesDelimiterWordContinuations(t *testing.T) {
	sources := []string{
		"cat <<E\\\nOF\nharmless\nEOF\ndoc-lattice linear",
		"cat <<\"E\\\nOF\"\nharmless\nEOF\ndoc-lattice linear",
		"cat <<E\\\nOF\nEOF\ndoc-lattice linear",
		"cat <<\"E\\\nOF\"\nEOF\ndoc-lattice linear",
	}
	for _, src := range sources {
		t.Run(src, func(t *testing.T) {
			resp, err := Certify(mustRequest(t, src))
			if err != nil {
				t.Fatal(err)
			}
			events := resp.Results[0].Events
			wantStart := strings.Index(src, "\\\n")
			if len(events) != 1 || events[0].Kind != "refusal" ||
				events[0].Code != "parser-divergence-guard" ||
				events[0].StartByte != wantStart || events[0].EndByte != wantStart+2 {
				t.Fatalf("events = %+v, want only delimiter guard at [%d, %d)", events, wantStart, wantStart+2)
			}
		})
	}
}

func TestHeredocGuardEmptyBodyDoesNotSuppressSiblingHit(t *testing.T) {
	const empty = "cat <<EMPTY\nEMPTY\n"
	const guarded = "cat <<EOF\n$\\\n(doc-lattice linear)\nEOF\n"
	for _, src := range []string{empty + guarded, guarded + empty} {
		t.Run(src, func(t *testing.T) {
			resp, err := Certify(mustRequest(t, src))
			if err != nil {
				t.Fatal(err)
			}
			events := resp.Results[0].Events
			wantStart := strings.Index(src, "\\\n")
			if len(events) != 1 || events[0].Kind != "refusal" ||
				events[0].Code != "parser-divergence-guard" || events[0].StartByte != wantStart {
				t.Fatalf("events = %+v, want only sibling guard at %d", events, wantStart)
			}
		})
	}
}

func TestHeredocGuardWorkUnitsChargeVisitedNodes(t *testing.T) {
	const guard = "cat <<EOF\n$\\\n(doc-lattice linear)\nEOF\n"
	largeSource := strings.Repeat("echo one; ", 256) + guard
	resp, err := Certify(mustRequest(t, guard, largeSource))
	if err != nil {
		t.Fatal(err)
	}
	if small, large := resp.Results[0].WorkUnits, resp.Results[1].WorkUnits; large <= small {
		t.Fatalf("larger guarded AST work_units = %d, want more than small AST's %d", large, small)
	}
}

func TestHeredocGuardWorkCarriesIntoCleanCandidateWalk(t *testing.T) {
	const src = "echo before \\\nafter"
	stmts := mustParse(t, src)
	guardRefusal, guardWork := scanHeredocGuard(src, stmts)
	if guardRefusal != nil || guardWork <= 0 {
		t.Fatalf("guard scan = (%+v, %d), want clean scan with positive visited-node work", guardRefusal, guardWork)
	}
	_, _, ordinaryWalkWork := walk(stmts, src)
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	want := guardWork + ordinaryWalkWork + 1
	if got := resp.Results[0].WorkUnits; got != want {
		t.Fatalf("work_units = %d, want guard %d + walk %d + source base = %d", got, guardWork, ordinaryWalkWork, want)
	}
}

func TestHeredocGuardCatchesParseableBodyVariants(t *testing.T) {
	sources := []string{
		"cat <<EOF\nfirst \\\ncontinued\nEOF\n",
		"cat <<-EOF\n\tfirst \\\n\tcontinued\n\tEOF\n",
	}
	for _, src := range sources {
		t.Run(src, func(t *testing.T) {
			got := heredocGuard(src, mustParse(t, src))
			wantStart := strings.Index(src, "\\\n")
			if got == nil || got.code != "parser-divergence-guard" ||
				got.startByte != wantStart || got.endByte != wantStart+2 {
				t.Fatalf("guard = %+v, want parser-divergence-guard at [%d, %d)", got, wantStart, wantStart+2)
			}
		})
	}
}

func TestHeredocGuardChoosesEarliestContinuation(t *testing.T) {
	const src = "cat <<A <<B\nfirst \\\ncontinued\nA\nsecond \\\ncontinued\nB\n"
	stmts := mustParse(t, src)
	if len(stmts) != 1 || len(stmts[0].Redirs) != 2 {
		t.Fatalf("parsed statements = %+v, want one statement with two heredocs", stmts)
	}
	stmts[0].Redirs[0], stmts[0].Redirs[1] = stmts[0].Redirs[1], stmts[0].Redirs[0]
	got := heredocGuard(src, stmts)
	wantStart := strings.Index(src, "\\\n")
	if got == nil || got.startByte != wantStart || got.endByte != wantStart+2 {
		t.Fatalf("guard = %+v, want earliest source hit [%d, %d) despite reversed AST edges", got, wantStart, wantStart+2)
	}
}

func TestHeredocGuardKeepsNoAnchorCasesFailClosed(t *testing.T) {
	sources := []string{
		"cat <<'E\\\nOF'\nharmless\nEOF\ndoc-lattice linear",
		"cat <<EOF\nbody \\\nEOF\ndoc-lattice linear",
		"cat <<EOF\nEO\\\nF\ndoc-lattice linear",
	}
	for _, src := range sources {
		t.Run(src, func(t *testing.T) {
			resp, err := Certify(mustRequest(t, src))
			if err != nil {
				t.Fatal(err)
			}
			events := resp.Results[0].Events
			if len(events) != 1 || events[0].Kind != "refusal" || events[0].Code != "syntax-error" {
				t.Fatalf("events = %+v, want only the pinned parser's terminal syntax-error", events)
			}
		})
	}
}

func TestHeredocGuardIgnoresBackslashNewlineOutsideHeredocs(t *testing.T) {
	sources := []string{
		"echo before \\\nafter",
		"# comment \\\ncontinued\n",
		"printf '%s' 'quoted \\\ndata'",
		"printf \"%s\" \"quoted \\\ndata\"",
		"cat <<<\"data \\\nmore\"",
		"cat >\"target \\\nname\"",
	}
	for _, src := range sources {
		t.Run(src, func(t *testing.T) {
			if got := heredocGuard(src, mustParse(t, src)); got != nil {
				t.Fatalf("non-heredoc source tripped guard: %+v", got)
			}
			resp, err := Certify(mustRequest(t, src))
			if err != nil {
				t.Fatal(err)
			}
			for _, event := range resp.Results[0].Events {
				if event.Kind == "refusal" && event.Code == "parser-divergence-guard" {
					t.Fatalf("non-heredoc source emitted guard refusal: %+v", resp.Results[0].Events)
				}
			}
		})
	}
}

func TestHeredocGuardFindsNestedRedirectAndIsolatesSources(t *testing.T) {
	const guarded = "doc-lattice before; echo \"$(cat <<EOF\n$\\\n(doc-lattice hidden)\nEOF\n)\"; doc-lattice after"
	const sibling = "doc-lattice sibling"
	resp, err := Certify(mustRequest(t, guarded, sibling))
	if err != nil {
		t.Fatal(err)
	}
	wantStart := strings.Index(guarded, "\\\n")
	guardEvents := resp.Results[0].Events
	if len(guardEvents) != 1 || guardEvents[0].Kind != "refusal" ||
		guardEvents[0].Code != "parser-divergence-guard" || guardEvents[0].StartByte != wantStart {
		t.Fatalf("guarded events = %+v, want only nested guard at %d", guardEvents, wantStart)
	}
	if got := commandHeads(t, resp.Results[1].Events); !reflect.DeepEqual(got, []string{"doc-lattice"}) {
		t.Fatalf("sibling command heads = %#v, want unaffected doc-lattice site", got)
	}
}

func TestHeredocGuardMalformedTreesDeferWithoutScanningGlobally(t *testing.T) {
	wordAt := func(offset uint, value string) *syntax.Word {
		return &syntax.Word{Parts: []syntax.WordPart{&syntax.Lit{
			ValuePos: syntax.NewPos(offset, 1, offset+1),
			ValueEnd: syntax.NewPos(offset+uint(len(value)), 1, offset+uint(len(value))+1),
			Value:    value,
		}}}
	}

	t.Run("invalid body span", func(t *testing.T) {
		const src = "EOF body \\\n"
		redirect := &syntax.Redirect{
			OpPos: syntax.NewPos(0, 1, 1),
			Op:    syntax.Hdoc,
			Word:  wordAt(0, "EOF"),
			Hdoc:  wordAt(100, "body"),
		}
		stmt := &syntax.Stmt{Position: syntax.NewPos(0, 1, 1), Redirs: []*syntax.Redirect{redirect}}
		got, work := scanHeredocGuard(src, []*syntax.Stmt{stmt})
		if got != nil {
			t.Fatalf("invalid AST span produced guessed guard: %+v", got)
		}
		if work <= 0 {
			t.Fatal("invalid AST scan discarded its visited-node work")
		}
	})

	t.Run("cycle", func(t *testing.T) {
		const src = "echo \\\ncontinued"
		substitution := &syntax.CmdSubst{}
		stmt := &syntax.Stmt{
			Position: syntax.NewPos(0, 1, 1),
			Cmd: &syntax.CallExpr{Args: []*syntax.Word{{
				Parts: []syntax.WordPart{substitution},
			}}},
		}
		substitution.Stmts = []*syntax.Stmt{stmt}
		got, work := scanHeredocGuard(src, []*syntax.Stmt{stmt})
		if got != nil {
			t.Fatalf("cyclic AST produced guard: %+v", got)
		}
		if work <= 0 {
			t.Fatal("cyclic AST scan discarded its visited-node work")
		}
	})

	t.Run("aliased redirect", func(t *testing.T) {
		const src = "EOF\\\n"
		redirect := &syntax.Redirect{
			OpPos: syntax.NewPos(0, 1, 1),
			Op:    syntax.Hdoc,
			Word:  wordAt(0, "EOF"),
			Hdoc:  wordAt(3, "\\\n"),
		}
		stmt := &syntax.Stmt{
			Position: syntax.NewPos(0, 1, 1),
			Redirs:   []*syntax.Redirect{redirect, redirect},
		}
		got, work := scanHeredocGuard(src, []*syntax.Stmt{stmt})
		if got != nil {
			t.Fatalf("aliased AST produced guard instead of deferring: %+v", got)
		}
		if work <= 0 {
			t.Fatal("aliased AST scan discarded its visited-node work")
		}
	})

	t.Run("depth cap", func(t *testing.T) {
		var part syntax.WordPart = &syntax.Lit{
			ValuePos: syntax.NewPos(0, 1, 1), ValueEnd: syntax.NewPos(1, 1, 2), Value: "x",
		}
		for range visitorDepthCap {
			part = &syntax.CmdSubst{Stmts: []*syntax.Stmt{{
				Position: syntax.NewPos(0, 1, 1),
				Cmd:      &syntax.CallExpr{Args: []*syntax.Word{{Parts: []syntax.WordPart{part}}}},
			}}}
		}
		root := &syntax.Stmt{
			Position: syntax.NewPos(0, 1, 1),
			Cmd:      &syntax.CallExpr{Args: []*syntax.Word{{Parts: []syntax.WordPart{part}}}},
		}
		got, work := scanHeredocGuard("x\\\n", []*syntax.Stmt{root})
		if got != nil {
			t.Fatalf("over-depth AST produced guard instead of deferring: %+v", got)
		}
		if work <= 0 {
			t.Fatal("over-depth AST scan discarded its visited-node work")
		}
	})
}

func TestWalkWithInitialWorkPreservesZeroAndSharesCap(t *testing.T) {
	const src = "echo ok"
	stmts := mustParse(t, src)
	wantSites, wantRefusals, wantWork := walk(stmts, src)
	gotSites, gotRefusals, gotWork := walkWithInitialWork(stmts, src, 0)
	if !reflect.DeepEqual(gotSites, wantSites) || !reflect.DeepEqual(gotRefusals, wantRefusals) || gotWork != wantWork {
		t.Fatalf("zero initial work changed walk: got (%+v, %+v, %d), want (%+v, %+v, %d)", gotSites, gotRefusals, gotWork, wantSites, wantRefusals, wantWork)
	}

	sites, refusals, work := walkWithInitialWork(stmts, src, visitorNodeCap)
	if len(sites) != 0 || len(refusals) != 1 || refusals[0].code != "work-cap" {
		t.Fatalf("cap-shared walk = (%+v, %+v), want no sites and one work-cap", sites, refusals)
	}
	if work <= visitorNodeCap {
		t.Fatalf("cap refusal work = %d, want charged initial work plus refusal", work)
	}
}
