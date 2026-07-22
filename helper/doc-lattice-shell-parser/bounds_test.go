// Package main tests layered source-certification bounds.
package main

import (
	"strings"
	"testing"
)

func TestSourceByteCapBoundaryAndIsolation(t *testing.T) {
	atLimit := strings.Repeat(" ", helperSourceCapBytes)
	overLimit := "$(" + strings.Repeat("a", helperSourceCapBytes-1)
	response, err := Certify(mustRequest(t, atLimit, overLimit, "doc-lattice check"))
	if err != nil {
		t.Fatal(err)
	}
	if containsRefusalCode(response.Results[0].Events, "source-cap") {
		t.Fatal("source at the byte cap was refused as over-cap")
	}
	requireOnlyTerminalCap(t, response.Results[1], "source-cap", len(overLimit))
	if sites := response.Results[2].Events; len(sites) != 1 || sites[0].Kind != "command_site" {
		t.Fatalf("sibling events = %#v, want one independently certified command site", sites)
	}
}

func TestStatementCapBoundaryAndSuppression(t *testing.T) {
	atLimit := strings.Repeat(":\n", statementCap)
	overLimit := atLimit + ":\n"
	response, err := Certify(mustRequest(t, atLimit, overLimit))
	if err != nil {
		t.Fatal(err)
	}
	if containsRefusalCode(response.Results[0].Events, "statement-cap") {
		t.Fatal("source at the statement cap was refused as over-cap")
	}
	requireOnlyTerminalCap(t, response.Results[1], "statement-cap", len(overLimit))
}

func TestVisitorCapBreachesSuppressEarlierFacts(t *testing.T) {
	tests := []struct {
		name string
		src  string
		code string
	}{
		{
			name: "event cap after command sites",
			src:  strings.Repeat(":\n", eventCap+1),
			code: "event-cap",
		},
		{
			name: "node work cap during certification",
			src:  strings.Repeat("x a a a a a\n", 8_000),
			code: "work-cap",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response, err := Certify(mustRequest(t, test.src))
			if err != nil {
				t.Fatal(err)
			}
			requireOnlyTerminalCap(t, response.Results[0], test.code, len(test.src))
		})
	}
}

func requireOnlyTerminalCap(t *testing.T, result Result, code string, srcLen int) {
	t.Helper()
	if len(result.Events) != 1 {
		var last Event
		if len(result.Events) > 0 {
			last = result.Events[len(result.Events)-1]
		}
		t.Fatalf("event count = %d (last = %#v), want only one terminal %s refusal", len(result.Events), last, code)
	}
	event := result.Events[0]
	if event.Kind != "refusal" || event.Code != code {
		t.Fatalf("event = %#v, want terminal %s refusal", event, code)
	}
	if reasonScopes[event.Code] != "terminal" {
		t.Fatalf("reason scope for %q = %q, want terminal", event.Code, reasonScopes[event.Code])
	}
	if err := validateRawSpan(event.StartByte, event.EndByte, srcLen); err != nil {
		t.Fatalf("cap span [%d, %d) is invalid for source length %d", event.StartByte, event.EndByte, srcLen)
	}
	if result.WorkUnits < 2 {
		t.Fatalf("work_units = %d, want base plus cap event", result.WorkUnits)
	}
}

func containsRefusalCode(events []Event, code string) bool {
	for _, event := range events {
		if event.Kind == "refusal" && event.Code == code {
			return true
		}
	}
	return false
}
