// Package main tests helper build identity reporting.
package main

import "testing"

func TestParserVersionMatchesPin(t *testing.T) {
	if got := parserVersion(); got != "mvdan.cc/sh/v3@v3.13.1" {
		t.Fatalf("parser version %q", got)
	}
}

func TestHelperVersionDefaultsToDevelopmentIdentity(t *testing.T) {
	if helperVersion != "dev-unset" {
		t.Fatalf("default helper version %q, want dev-unset", helperVersion)
	}
}

func TestCertifyReportsBuildIdentities(t *testing.T) {
	response, err := Certify(&Request{
		ProtocolVersion: 1,
		Sources:         []Source{{ID: 0, Source: "true"}},
	})
	if err != nil {
		t.Fatalf("Certify returned an error: %v", err)
	}
	if response.HelperVersion != helperVersion {
		t.Fatalf("helper version %q, want %q", response.HelperVersion, helperVersion)
	}
	if response.ParserVersion != parserVersion() {
		t.Fatalf("parser version %q, want %q", response.ParserVersion, parserVersion())
	}
}
