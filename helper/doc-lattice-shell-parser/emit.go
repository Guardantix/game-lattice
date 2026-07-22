// Package main emits frozen wire facts from certified shell syntax.
package main

import (
	"errors"
	"sort"
	"strings"

	"mvdan.cc/sh/v3/expand"
	"mvdan.cc/sh/v3/syntax"
)

var errInvalidEmission = errors.New("invalid syntax facts")

type orderedEvent struct {
	event           Event
	originalOrdinal int
}

func certifySource(source Source) (Result, error) {
	statements, parseRefusal := parseStatements(source.Source)
	sites, walkRefusals, work := walk(statements, source.Source)
	events, err := emitCommandSites(sites, source.Source)
	if err != nil {
		return Result{}, err
	}
	combined := make([]orderedEvent, 0, len(events)+1)
	for index, event := range events {
		combined = append(combined, orderedEvent{event: event, originalOrdinal: index})
	}
	if len(walkRefusals) > 1 {
		return Result{}, errInvalidEmission
	}
	var terminal *rawRefusal
	if len(walkRefusals) == 1 {
		terminal = &walkRefusals[0]
	} else {
		terminal = parseRefusal
	}
	if terminal != nil {
		if err := validateRawSpan(terminal.startByte, terminal.endByte, len(source.Source)); err != nil {
			return Result{}, err
		}
		combined = append(combined, orderedEvent{
			event: Event{
				Kind:      "refusal",
				Code:      terminal.code,
				StartByte: terminal.startByte,
				EndByte:   terminal.endByte,
			},
			originalOrdinal: len(combined),
		})
	}
	sort.SliceStable(combined, func(left, right int) bool {
		x, y := combined[left], combined[right]
		if x.event.StartByte != y.event.StartByte {
			return x.event.StartByte < y.event.StartByte
		}
		xKind, yKind := eventKindOrdinal(x.event.Kind), eventKindOrdinal(y.event.Kind)
		if xKind != yKind {
			return xKind < yKind
		}
		return x.originalOrdinal < y.originalOrdinal
	})
	resultEvents := make([]Event, len(combined))
	for index, event := range combined {
		resultEvents[index] = event.event
		if event.event.Kind == "refusal" && index != len(combined)-1 {
			return Result{}, errInvalidEmission
		}
	}
	return Result{ID: source.ID, Events: resultEvents, WorkUnits: work + 1}, nil
}

func eventKindOrdinal(kind string) int {
	if kind == "command_site" {
		return 0
	}
	return 1
}

func validateRawSpan(start, end, srcLen int) error {
	if start < 0 || start > end || end > srcLen {
		return errInvalidEmission
	}
	return nil
}

func emitCommandSites(sites []commandSite, src string) ([]Event, error) {
	events := make([]Event, 0, len(sites))
	for ordinal, site := range sites {
		event, err := emitCommandSite(site, ordinal, src)
		if err != nil {
			return nil, err
		}
		events = append(events, event)
	}
	return events, nil
}

func emitCommandSite(site commandSite, ordinal int, src string) (Event, error) {
	if site.call == nil || (len(site.call.Assigns) == 0 && len(site.call.Args) == 0) {
		return Event{}, errInvalidEmission
	}
	if len(site.assignments) > maxAssignmentsPerSite || len(site.argv) > maxArgvWordsPerSite {
		return Event{}, errInvalidEmission
	}
	start, end, err := validatedSpan(site.call, len(src))
	if err != nil {
		return Event{}, err
	}
	event := Event{
		Kind:        "command_site",
		Ordinal:     ordinal,
		StartByte:   start,
		EndByte:     end,
		Assignments: make([]Assignment, 0, len(site.assignments)),
		Argv:        make([]Word, 0, len(site.argv)),
	}
	for _, raw := range site.assignments {
		if raw == nil || raw.Name == nil || !validAssignmentName(raw.Name.Value) {
			return Event{}, errInvalidEmission
		}
		assignStart, assignEnd, err := validatedSpan(raw, len(src))
		if err != nil {
			return Event{}, err
		}
		event.Assignments = append(event.Assignments, Assignment{
			Name:       raw.Name.Value,
			ValueKnown: wordIsStaticLiteral(raw.Value, src),
			StartByte:  assignStart,
			EndByte:    assignEnd,
		})
	}
	for _, raw := range site.argv {
		if raw == nil || len(raw.Parts) == 0 {
			return Event{}, errInvalidEmission
		}
		wordStart, wordEnd, err := validatedSpan(raw, len(src))
		if err != nil {
			return Event{}, err
		}
		text, known := literalWord(raw, src)
		word := Word{Single: wordIsSingle(raw, src), StartByte: wordStart, EndByte: wordEnd}
		if known {
			word.Text = &text
			word.Single = true
		}
		event.Argv = append(event.Argv, word)
	}
	return event, nil
}

func validAssignmentName(name string) bool {
	if name == "" || !isAssignmentNameStart(name[0]) {
		return false
	}
	for index := 1; index < len(name); index++ {
		if !isAssignmentNameStart(name[index]) && (name[index] < '0' || name[index] > '9') {
			return false
		}
	}
	return true
}

func isAssignmentNameStart(char byte) bool {
	return char == '_' || char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z'
}

func validatedSpan(node syntax.Node, srcLen int) (start, end int, err error) {
	defer func() {
		if recover() != nil {
			start, end, err = 0, 0, errInvalidEmission
		}
	}()
	if node == nil {
		return 0, 0, errInvalidEmission
	}
	startPos, endPos := node.Pos(), node.End()
	if !startPos.IsValid() || !endPos.IsValid() {
		return 0, 0, errInvalidEmission
	}
	startOffset, endOffset := uint64(startPos.Offset()), uint64(endPos.Offset())
	if startOffset > endOffset || endOffset > uint64(srcLen) {
		return 0, 0, errInvalidEmission
	}
	return int(startOffset), int(endOffset), nil
}

func wordIsStaticLiteral(word *syntax.Word, src string) bool {
	if word == nil {
		return true
	}
	_, known := literalWord(word, src)
	return known && !hasAssignmentColonTilde(word, src)
}

func hasAssignmentColonTilde(word *syntax.Word, src string) bool {
	for _, part := range word.Parts {
		literal, ok := part.(*syntax.Lit)
		if !ok || literal == nil || !literal.Pos().IsValid() || !literal.End().IsValid() {
			continue
		}
		start, end := int(literal.Pos().Offset()), int(literal.End().Offset())
		if start < 0 || start > end || end > len(src) {
			continue
		}
		raw := src[start:end]
		for index := 0; index+1 < len(raw); index++ {
			if raw[index] == '\\' {
				index++
				continue
			}
			if raw[index] == ':' && raw[index+1] == '~' {
				return true
			}
		}
	}
	return false
}

func literalWord(word *syntax.Word, src string) (string, bool) {
	if word == nil {
		return "", true
	}
	var value strings.Builder
	for _, part := range word.Parts {
		partValue, ok := literalWordPart(part, src, false, word)
		if !ok {
			return "", false
		}
		value.WriteString(partValue)
	}
	return value.String(), true
}

func literalWordPart(part syntax.WordPart, src string, quoted bool, word *syntax.Word) (string, bool) {
	switch part := part.(type) {
	case *syntax.Lit:
		if part != nil && (quoted || !unquotedLiteralIsDynamic(part, word, src)) {
			return decodedLiteral(part, src, quoted)
		}
	case *syntax.SglQuoted:
		if part != nil {
			if !part.Dollar {
				return part.Value, true
			}
			value, _, err := expand.Format(nil, part.Value, nil)
			if err != nil {
				return "", false
			}
			value, _, _ = strings.Cut(value, "\x00")
			return value, true
		}
	case *syntax.DblQuoted:
		if part == nil || part.Dollar {
			return "", false
		}
		var value strings.Builder
		for _, nested := range part.Parts {
			nestedValue, ok := literalWordPart(nested, src, true, word)
			if !ok {
				return "", false
			}
			value.WriteString(nestedValue)
		}
		return value.String(), true
	}
	return "", false
}

func decodedLiteral(literal *syntax.Lit, src string, doubleQuoted bool) (string, bool) {
	if literal == nil || !literal.Pos().IsValid() || !literal.End().IsValid() {
		return "", false
	}
	start, end := int(literal.Pos().Offset()), int(literal.End().Offset())
	if start < 0 || start > end || end > len(src) {
		return "", false
	}
	raw := src[start:end]
	var decoded strings.Builder
	for index := 0; index < len(raw); index++ {
		if raw[index] != '\\' || index+1 >= len(raw) {
			decoded.WriteByte(raw[index])
			continue
		}
		next := raw[index+1]
		if next == '\n' {
			index++
			continue
		}
		if !doubleQuoted || next == '$' || next == '`' || next == '"' || next == '\\' {
			decoded.WriteByte(next)
			index++
			continue
		}
		decoded.WriteByte(raw[index])
	}
	return decoded.String(), true
}

func wordIsSingle(word *syntax.Word, src string) bool {
	if word == nil || len(word.Parts) == 0 {
		return false
	}
	for _, part := range word.Parts {
		switch part := part.(type) {
		case *syntax.Lit:
			if part == nil || unquotedLiteralIsDynamic(part, word, src) {
				return false
			}
		case *syntax.SglQuoted:
			if part == nil {
				return false
			}
		case *syntax.DblQuoted:
			if part == nil || !doubleQuotedIsSingle(part) {
				return false
			}
		case *syntax.ProcSubst:
			if part == nil {
				return false
			}
		default:
			return false
		}
	}
	return true
}

func doubleQuotedIsSingle(quoted *syntax.DblQuoted) bool {
	if quoted == nil {
		return false
	}
	for _, part := range quoted.Parts {
		switch part := part.(type) {
		case *syntax.Lit:
			if part == nil {
				return false
			}
		case *syntax.ParamExp:
			if quotedParameterMayExpandToMany(part) {
				return false
			}
		case *syntax.CmdSubst, *syntax.ArithmExp, *syntax.ProcSubst:
			continue
		default:
			return false
		}
	}
	return true
}

func quotedParameterMayExpandToMany(parameter *syntax.ParamExp) bool {
	if parameter == nil || parameter.Param == nil {
		return true
	}
	if parameter.Length || parameter.Width || parameter.IsSet {
		return false
	}
	if parameter.Param.Value == "@" || parameter.Names == syntax.NamesPrefixWords {
		return true
	}
	index, ok := parameter.Index.(*syntax.Word)
	return ok && index != nil && index.Lit() == "@"
}

func unquotedLiteralIsDynamic(literal *syntax.Lit, word *syntax.Word, src string) bool {
	if literal == nil || word == nil || !literal.Pos().IsValid() || !literal.End().IsValid() || !word.Pos().IsValid() {
		return true
	}
	start, end := int(literal.Pos().Offset()), int(literal.End().Offset())
	if start < 0 || start > end || end > len(src) {
		return true
	}
	raw := src[start:end]
	if start == int(word.Pos().Offset()) && len(raw) > 0 && raw[0] == '~' {
		return true
	}
	return hasActiveGlob(raw) || hasActiveBrace(raw)
}

func hasActiveGlob(raw string) bool {
	for index := 0; index < len(raw); index++ {
		if raw[index] == '\\' {
			index++
			continue
		}
		switch raw[index] {
		case '*', '?':
			return true
		case '[':
			for close := index + 1; close < len(raw); close++ {
				if raw[close] == '\\' {
					close++
					continue
				}
				if raw[close] == ']' {
					return true
				}
			}
		}
	}
	return false
}

func hasActiveBrace(raw string) bool {
	open := -1
	separator := false
	for index := 0; index < len(raw); index++ {
		if raw[index] == '\\' {
			index++
			continue
		}
		switch raw[index] {
		case '{':
			open, separator = index, false
		case ',':
			separator = separator || open >= 0
		case '.':
			separator = separator || open >= 0 && index+1 < len(raw) && raw[index+1] == '.'
		case '}':
			if open >= 0 && separator {
				return true
			}
			open, separator = -1, false
		}
	}
	return false
}
