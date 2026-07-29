// Package fingerprint implements semantic-fingerprint/v1 for the Go boundary.
package fingerprint

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

const (
	SpecVersion         = "semantic-fingerprint/v1"
	VolatilePathVersion = "volatile-pointers/v1"
	maxSafeInteger      = int64(9_007_199_254_740_991)
	minSafeInteger      = -maxSafeInteger
)

var (
	ErrInvalidJSON       = errors.New("fingerprint: invalid JSON")
	ErrNonCanonicalValue = errors.New("fingerprint: value is outside the canonical domain")
	ErrInvalidPointer    = errors.New("fingerprint: invalid volatile JSON Pointer")
)

// SemanticFingerprint strips exact volatile object paths, applies the restricted
// RFC 8785 canonical form, and returns a lowercase SHA-256 digest.
func SemanticFingerprint(raw []byte, volatilePointers []string) (string, error) {
	canonical, err := Canonicalize(raw, volatilePointers)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:]), nil
}

// Canonicalize accepts only UTF-8 I-JSON values used by semantic-fingerprint/v1.
// Binary/non-integral JSON numbers and integers outside the shared safe range
// are rejected; those values belong in canonical decimal strings.
func Canonicalize(raw []byte, volatilePointers []string) ([]byte, error) {
	if !utf8.Valid(raw) {
		return nil, fmt.Errorf("%w: input is not UTF-8", ErrInvalidJSON)
	}
	if err := rejectDuplicateObjectKeys(raw); err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidJSON, err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, fmt.Errorf("%w: multiple JSON values", ErrInvalidJSON)
		}
		return nil, fmt.Errorf("%w: %v", ErrInvalidJSON, err)
	}
	root, ok := value.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("%w: root must be an object", ErrNonCanonicalValue)
	}
	for _, pointer := range volatilePointers {
		if err := removePointer(root, pointer); err != nil {
			return nil, err
		}
	}
	var output bytes.Buffer
	if err := writeCanonical(&output, root); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func rejectDuplicateObjectKeys(raw []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var walk func() error
	walk = func() error {
		token, err := decoder.Token()
		if err != nil {
			return fmt.Errorf("%w: %v", ErrInvalidJSON, err)
		}
		delim, isDelimiter := token.(json.Delim)
		if !isDelimiter {
			return nil
		}
		switch delim {
		case '{':
			seen := make(map[string]struct{})
			for decoder.More() {
				keyToken, err := decoder.Token()
				if err != nil {
					return fmt.Errorf("%w: %v", ErrInvalidJSON, err)
				}
				key, ok := keyToken.(string)
				if !ok {
					return fmt.Errorf("%w: object key is not a string", ErrInvalidJSON)
				}
				if _, exists := seen[key]; exists {
					return fmt.Errorf(
						"%w: duplicate object key %q",
						ErrInvalidJSON,
						key,
					)
				}
				seen[key] = struct{}{}
				if err := walk(); err != nil {
					return err
				}
			}
			if _, err := decoder.Token(); err != nil {
				return fmt.Errorf("%w: %v", ErrInvalidJSON, err)
			}
		case '[':
			for decoder.More() {
				if err := walk(); err != nil {
					return err
				}
			}
			if _, err := decoder.Token(); err != nil {
				return fmt.Errorf("%w: %v", ErrInvalidJSON, err)
			}
		default:
			return fmt.Errorf("%w: unexpected delimiter %q", ErrInvalidJSON, delim)
		}
		return nil
	}
	if err := walk(); err != nil {
		return err
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return fmt.Errorf("%w: multiple JSON values", ErrInvalidJSON)
		}
		return fmt.Errorf("%w: %v", ErrInvalidJSON, err)
	}
	return nil
}

func removePointer(root map[string]any, pointer string) error {
	parts, err := pointerParts(pointer)
	if err != nil {
		return err
	}
	var current any = root
	for _, part := range parts[:len(parts)-1] {
		switch value := current.(type) {
		case map[string]any:
			next, exists := value[part]
			if !exists {
				return nil
			}
			current = next
		case []any:
			return fmt.Errorf("%w: %q traverses an array", ErrInvalidPointer, pointer)
		default:
			return nil
		}
	}
	switch parent := current.(type) {
	case map[string]any:
		delete(parent, parts[len(parts)-1])
		return nil
	case []any:
		return fmt.Errorf("%w: %q targets an array", ErrInvalidPointer, pointer)
	default:
		return nil
	}
}

func pointerParts(pointer string) ([]string, error) {
	if !strings.HasPrefix(pointer, "/") || pointer == "/" {
		return nil, fmt.Errorf(
			"%w: %q must be a non-root pointer",
			ErrInvalidPointer,
			pointer,
		)
	}
	rawParts := strings.Split(pointer[1:], "/")
	parts := make([]string, 0, len(rawParts))
	for _, raw := range rawParts {
		var decoded strings.Builder
		for index := 0; index < len(raw); index++ {
			if raw[index] != '~' {
				decoded.WriteByte(raw[index])
				continue
			}
			if index+1 >= len(raw) || (raw[index+1] != '0' && raw[index+1] != '1') {
				return nil, fmt.Errorf(
					"%w: %q contains an invalid escape",
					ErrInvalidPointer,
					pointer,
				)
			}
			if raw[index+1] == '0' {
				decoded.WriteByte('~')
			} else {
				decoded.WriteByte('/')
			}
			index++
		}
		parts = append(parts, decoded.String())
	}
	return parts, nil
}

func writeCanonical(output *bytes.Buffer, value any) error {
	switch typed := value.(type) {
	case nil:
		output.WriteString("null")
	case bool:
		if typed {
			output.WriteString("true")
		} else {
			output.WriteString("false")
		}
	case string:
		writeString(output, typed)
	case json.Number:
		rendered, err := canonicalInteger(typed.String())
		if err != nil {
			return err
		}
		output.WriteString(rendered)
	case []any:
		output.WriteByte('[')
		for index, item := range typed {
			if index > 0 {
				output.WriteByte(',')
			}
			if err := writeCanonical(output, item); err != nil {
				return err
			}
		}
		output.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Slice(keys, func(left, right int) bool {
			return utf16Less(keys[left], keys[right])
		})
		output.WriteByte('{')
		for index, key := range keys {
			if index > 0 {
				output.WriteByte(',')
			}
			writeString(output, key)
			output.WriteByte(':')
			if err := writeCanonical(output, typed[key]); err != nil {
				return err
			}
		}
		output.WriteByte('}')
	default:
		return fmt.Errorf(
			"%w: unsupported %T",
			ErrNonCanonicalValue,
			value,
		)
	}
	return nil
}

func canonicalInteger(raw string) (string, error) {
	if strings.ContainsAny(raw, ".eE") {
		return "", fmt.Errorf(
			"%w: non-integral number %q must be a decimal string",
			ErrNonCanonicalValue,
			raw,
		)
	}
	value, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || value < minSafeInteger || value > maxSafeInteger {
		return "", fmt.Errorf(
			"%w: integer %q exceeds the safe domain",
			ErrNonCanonicalValue,
			raw,
		)
	}
	return strconv.FormatInt(value, 10), nil
}

func utf16Less(left, right string) bool {
	leftUnits := utf16.Encode([]rune(left))
	rightUnits := utf16.Encode([]rune(right))
	for index := 0; index < len(leftUnits) && index < len(rightUnits); index++ {
		if leftUnits[index] != rightUnits[index] {
			return leftUnits[index] < rightUnits[index]
		}
	}
	return len(leftUnits) < len(rightUnits)
}

func writeString(output *bytes.Buffer, value string) {
	output.WriteByte('"')
	for _, character := range value {
		switch character {
		case '"', '\\':
			output.WriteByte('\\')
			output.WriteRune(character)
		case '\b':
			output.WriteString(`\b`)
		case '\t':
			output.WriteString(`\t`)
		case '\n':
			output.WriteString(`\n`)
		case '\f':
			output.WriteString(`\f`)
		case '\r':
			output.WriteString(`\r`)
		default:
			if character < 0x20 {
				fmt.Fprintf(output, `\u%04x`, character)
			} else {
				output.WriteRune(character)
			}
		}
	}
	output.WriteByte('"')
}
