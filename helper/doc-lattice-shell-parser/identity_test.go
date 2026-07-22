// Package main tests helper build identity reporting.
package main

import (
	"runtime/debug"
	"testing"
)

func TestParserVersionMatchesPin(t *testing.T) {
	if got := parserVersion(); got != "mvdan.cc/sh/v3@v3.13.1" {
		t.Fatalf("parser version %q", got)
	}
}

func TestParserDependencyVersionRejectsReplacement(t *testing.T) {
	dependency := &debug.Module{
		Path:    pinnedParserModule,
		Version: pinnedParserVersion,
		Replace: &debug.Module{Path: "../parser-fork"},
	}

	got, found := parserDependencyVersion(dependency)
	if !found {
		t.Fatal("pinned parser dependency was not recognized")
	}
	if got != "mvdan.cc/sh/v3@replaced" {
		t.Fatalf("replacement parser version %q, want fail-closed sentinel", got)
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
