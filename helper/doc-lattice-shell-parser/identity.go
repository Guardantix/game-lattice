// Package main identifies the helper and its pinned parser dependency.
package main

import "runtime/debug"

const (
	pinnedParserModule  = "mvdan.cc/sh/v3"
	pinnedParserVersion = "v3.13.1"
)

// helperVersion is replaced with the manifest digest by the release build wrapper.
var helperVersion = "dev-unset"

// parserVersion returns the parser module identity recorded in Go build metadata.
func parserVersion() string {
	if build, ok := debug.ReadBuildInfo(); ok {
		for _, dependency := range build.Deps {
			if dependency.Path == pinnedParserModule && dependency.Version != "" {
				return dependency.Path + "@" + dependency.Version
			}
		}
	}
	// Release builds carry dependency build information. The fallback keeps direct
	// source and test builds tied to the same frozen parser pin.
	return pinnedParserModule + "@" + pinnedParserVersion
}
