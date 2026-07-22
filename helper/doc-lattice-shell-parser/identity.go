// Package main identifies the helper and its pinned parser dependency.
package main

import "runtime/debug"

const (
	pinnedParserModule  = "mvdan.cc/sh/v3"
	pinnedParserVersion = "v3.13.1"
	replacedParserLabel = "mvdan.cc/sh/v3@replaced"
	unknownParserLabel  = "mvdan.cc/sh/v3@unknown"
)

// helperVersion is replaced with the manifest digest by the release build wrapper.
var helperVersion = "dev-unset"

// parserVersion returns the parser module identity recorded in Go build metadata.
func parserVersion() string {
	if build, ok := debug.ReadBuildInfo(); ok {
		for _, dependency := range build.Deps {
			if version, found := parserDependencyVersion(dependency); found {
				return version
			}
		}
	}
	// Release builds carry dependency build information. The fallback keeps direct
	// source and test builds tied to the same frozen parser pin.
	return pinnedParserModule + "@" + pinnedParserVersion
}

func parserDependencyVersion(dependency *debug.Module) (string, bool) {
	if dependency == nil || dependency.Path != pinnedParserModule {
		return "", false
	}
	if dependency.Replace != nil {
		return replacedParserLabel, true
	}
	if dependency.Version == "" {
		return unknownParserLabel, true
	}
	return dependency.Path + "@" + dependency.Version, true
}
