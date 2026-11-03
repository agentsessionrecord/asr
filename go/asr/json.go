// Package asr contains generated ASR 0.1 shapes. Use a schema validator to check
// constraints and relationships. JSON numbers retain their original spelling.
package asr

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// Optional distinguishes an omitted field, an explicit null, and a value.
// Omitted fields require Go 1.24 or later for encoding/json's omitzero tag.
type Optional[T any] struct {
	Value   T
	Present bool
	Null    bool
}

func Some[T any](value T) Optional[T] { return Optional[T]{Value: value, Present: true} }
func Null[T any]() Optional[T]        { return Optional[T]{Present: true, Null: true} }
func (v Optional[T]) IsZero() bool    { return !v.Present }
func (v Optional[T]) MarshalJSON() ([]byte, error) {
	if !v.Present || v.Null {
		return []byte("null"), nil
	}
	return json.Marshal(v.Value)
}
func (v *Optional[T]) UnmarshalJSON(data []byte) error {
	var value T
	isNull := bytes.Equal(bytes.TrimSpace(data), []byte("null"))
	if !isNull {
		if err := json.Unmarshal(data, &value); err != nil {
			return err
		}
	}
	*v = Optional[T]{Value: value, Present: true, Null: isNull}
	return nil
}

func marshalObject(value any, extra map[string]json.RawMessage, keys ...string) ([]byte, error) {
	data, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var object map[string]json.RawMessage
	if err := json.Unmarshal(data, &object); err != nil {
		return nil, err
	}
	known := make(map[string]bool, len(keys))
	for _, key := range keys {
		known[key] = true
	}
	for key, value := range extra {
		if known[key] {
			return nil, fmt.Errorf("extra field shadows schema field %q", key)
		}
		object[key] = value
	}
	return json.Marshal(object)
}

func unmarshalObject(data []byte, value any, keys ...string) (map[string]json.RawMessage, error) {
	var object map[string]json.RawMessage
	if err := json.Unmarshal(data, &object); err != nil {
		return nil, err
	}
	if object == nil {
		return nil, fmt.Errorf("expected a JSON object")
	}
	if err := json.Unmarshal(data, value); err != nil {
		return nil, err
	}
	for _, key := range keys {
		delete(object, key)
	}
	return object, nil
}
