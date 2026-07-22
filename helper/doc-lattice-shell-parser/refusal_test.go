// Package main tests fail-closed refusal emission.
package main

import (
	"encoding/json"
	"reflect"
	"testing"

	"mvdan.cc/sh/v3/syntax"
)

func refusalCodes(events []Event) []string {
	codes := make([]string, 0)
	for _, event := range events {
		if event.Kind == "refusal" {
			codes = append(codes, event.Code)
		}
	}
	return codes
}

func commandHeads(t *testing.T, events []Event) []string {
	t.Helper()
	heads := make([]string, 0)
	for _, event := range events {
		if event.Kind != "command_site" {
			continue
		}
		if len(event.Argv) == 0 || event.Argv[0].Text == nil {
			t.Fatalf("command site has no static head: %#v", event)
		}
		heads = append(heads, *event.Argv[0].Text)
	}
	return heads
}

func TestRefusalCodesAreHelperScoped(t *testing.T) {
	sources := []string{
		`cat <(doc-lattice check)`,
		`A=*($(doc-lattice hidden)|b) echo outer; doc-lattice later`,
		`((1)); doc-lattice later`,
	}
	resp, err := Certify(mustRequest(t, sources...))
	if err != nil {
		t.Fatal(err)
	}
	for _, result := range resp.Results {
		got := refusalCodes(result.Events)
		if len(got) == 0 {
			t.Fatalf("result %d has no refusal event: %#v", result.ID, result.Events)
		}
		for _, code := range got {
			scope := reasonScopes[code]
			if scope != "terminal" && scope != "subtree-local" {
				t.Fatalf("helper emitted code %q with scope %q", code, scope)
			}
		}
	}
}

func TestProcSubstIsTerminalUnsupportedConstruct(t *testing.T) {
	const src = `cat <(doc-lattice hidden); doc-lattice later`
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	if got := commandHeads(t, events); !reflect.DeepEqual(got, []string{"cat"}) {
		t.Fatalf("command heads = %#v, want only the completed outer command", got)
	}
	if got := refusalCodes(events); !reflect.DeepEqual(got, []string{"unsupported-construct"}) {
		t.Fatalf("refusal codes = %#v, want terminal unsupported-construct", got)
	}
	last := events[len(events)-1]
	if last.Kind != "refusal" || reasonScopes[last.Code] != "terminal" {
		t.Fatalf("terminal refusal must be last, got %#v", last)
	}
}

func TestArithmCmdTerminalSuppressesLaterSibling(t *testing.T) {
	const src = `((1)); doc-lattice later`
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	if got := commandHeads(t, events); len(got) != 0 {
		t.Fatalf("command heads = %#v, want terminal refusal to suppress later sibling", got)
	}
	if got := refusalCodes(events); !reflect.DeepEqual(got, []string{"unsupported-construct"}) {
		t.Fatalf("refusal codes = %#v, want terminal unsupported-construct", got)
	}
}

func TestUnsupportedExpansionRefusesLocallyWithoutLeakingNestedSite(t *testing.T) {
	const src = `A=*($(doc-lattice hidden)|b) echo outer; doc-lattice later`
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	if got := commandHeads(t, events); !reflect.DeepEqual(got, []string{"echo", "doc-lattice"}) {
		t.Fatalf("command heads = %#v, want outer and later sites without nested hidden site", got)
	}
	if got := refusalCodes(events); !reflect.DeepEqual(got, []string{"expansion-unsupported"}) {
		t.Fatalf("refusal codes = %#v, want one expansion-unsupported", got)
	}
	refusalIndex := indexOfEventKind(events, "refusal", 0)
	laterIndex := indexOfEventKind(events, "command_site", 1)
	if refusalIndex < 0 || laterIndex < 0 || refusalIndex >= laterIndex {
		t.Fatalf("events are not in local-refusal then later-site order: %#v", events)
	}
	if events[refusalIndex].EndByte > events[laterIndex].StartByte {
		t.Fatalf("local refusal overlaps later site: refusal %#v, site %#v", events[refusalIndex], events[laterIndex])
	}
}

func TestMultipleLocalRefusalsAndLaterSiteStayInSourceOrder(t *testing.T) {
	const src = `A=*($(doc-lattice hidden)|b) echo first; A=*($(doc-lattice buried)|b) echo second; doc-lattice later`
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	if got := commandHeads(t, events); !reflect.DeepEqual(got, []string{"echo", "echo", "doc-lattice"}) {
		t.Fatalf("command heads = %#v, want both outer commands and later site", got)
	}
	if got := refusalCodes(events); !reflect.DeepEqual(got, []string{"expansion-unsupported", "expansion-unsupported"}) {
		t.Fatalf("refusal codes = %#v, want two expansion-local refusals", got)
	}
	previousStart := -1
	for _, event := range events {
		if event.StartByte < previousStart {
			t.Fatalf("events are out of source order: %#v", events)
		}
		previousStart = event.StartByte
	}
	for index, event := range events {
		if event.Kind != "refusal" {
			continue
		}
		for _, later := range events[index+1:] {
			if later.Kind == "command_site" && event.EndByte > later.StartByte {
				t.Fatalf("local refusal %#v overlaps later site %#v", event, later)
			}
		}
	}
}

func TestUnsupportedRedirectOperatorRefusesLocallyAtCompleteSpan(t *testing.T) {
	const src = `>x; doc-lattice later`
	stmts, parseRefusal := parseStatements(src)
	if parseRefusal != nil {
		t.Fatalf("parseStatements refusal = %#v, want none", parseRefusal)
	}
	stmts[0].Redirs[0].Op = syntax.RedirOperator(255)
	sites, refusals, _ := walk(stmts, src)
	if len(sites) != 1 || len(sites[0].argv) == 0 || sites[0].argv[0].Lit() != "doc-lattice" {
		t.Fatalf("sites = %#v, want only the certified next sibling", sites)
	}
	if len(refusals) != 1 || refusals[0].code != "redirect-unsupported" {
		t.Fatalf("refusals = %#v, want one redirect-unsupported", refusals)
	}
	if refusals[0].startByte != 0 || refusals[0].endByte != 2 {
		t.Fatalf("redirect refusal span = [%d, %d), want complete redirect span [0, 2)", refusals[0].startByte, refusals[0].endByte)
	}
}

func TestTerminalParseRefusalIsLastAfterCompletedStatement(t *testing.T) {
	const src = `doc-lattice check; echo "$(`
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	if got := commandHeads(t, events); !reflect.DeepEqual(got, []string{"doc-lattice"}) {
		t.Fatalf("command heads = %#v, want retained completed statement", got)
	}
	last := events[len(events)-1]
	if last.Kind != "refusal" || last.Code != "syntax-error" {
		t.Fatalf("terminal refusal must be last, got %#v", last)
	}
}

func TestTerminalParseRefusalFollowsLocalRefusal(t *testing.T) {
	const src = `A=*($(doc-lattice hidden)|b) echo outer; echo "$(`
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	if got := commandHeads(t, events); !reflect.DeepEqual(got, []string{"echo"}) {
		t.Fatalf("command heads = %#v, want retained completed outer statement", got)
	}
	if got := refusalCodes(events); !reflect.DeepEqual(got, []string{"expansion-unsupported", "syntax-error"}) {
		t.Fatalf("refusal codes = %#v, want local expansion then terminal parse refusal", got)
	}
	last := events[len(events)-1]
	if last.Kind != "refusal" || last.Code != "syntax-error" {
		t.Fatalf("terminal parse refusal must be last, got %#v", last)
	}
}

func TestInvalidGeneratedRuleCodeFailsClosed(t *testing.T) {
	key := constructKey{node: "ExtGlob", role: "*"}
	original := certifiedConstructs[key]
	t.Cleanup(func() { certifiedConstructs[key] = original })

	for _, invalidCode := range []string{"not-owned-by-helper", "assignment-prefix"} {
		t.Run(invalidCode, func(t *testing.T) {
			rule := original
			rule.code = invalidCode
			certifiedConstructs[key] = rule

			const src = `A=*($(doc-lattice hidden)|b) echo outer; doc-lattice later`
			resp, err := Certify(mustRequest(t, src))
			if err != nil {
				return
			}
			events := resp.Results[0].Events
			for _, event := range events {
				if event.Kind == "refusal" && event.Code == invalidCode {
					t.Fatalf("helper emitted invalid generated code %q: %#v", invalidCode, events)
				}
			}
			last := events[len(events)-1]
			if last.Kind != "refusal" || last.Code != "unsupported-construct" || reasonScopes[last.Code] != "terminal" {
				t.Fatalf("invalid generated code did not fail closed with an owned terminal refusal: %#v", events)
			}
		})
	}
}

func TestRefusalWireFormIsFrozen(t *testing.T) {
	payload, err := json.Marshal(Event{Kind: "refusal", Code: "unsupported-construct", StartByte: 4, EndByte: 9})
	if err != nil {
		t.Fatal(err)
	}
	const want = `{"kind":"refusal","code":"unsupported-construct","start_byte":4,"end_byte":9}`
	if string(payload) != want {
		t.Fatalf("refusal JSON = %s, want %s", payload, want)
	}
}

func indexOfEventKind(events []Event, kind string, occurrence int) int {
	for index, event := range events {
		if event.Kind == kind {
			if occurrence == 0 {
				return index
			}
			occurrence--
		}
	}
	return -1
}
