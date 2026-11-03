package asr

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func decoded(t *testing.T, data []byte) any {
	t.Helper()
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		t.Fatal(err)
	}
	return value
}

func roundTrip(t *testing.T, input []byte, target any) []byte {
	t.Helper()
	if err := json.Unmarshal(input, target); err != nil {
		t.Fatal(err)
	}
	output, err := json.Marshal(target)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(decoded(t, input), decoded(t, output)) {
		t.Fatalf("JSON values changed during round trip: %s", input)
	}
	return output
}

func TestOptionalOmittedNullFalseZeroAndEmpty(t *testing.T) {
	var settings AgentSettings
	input := []byte(`{"mode":null,"approval":false,"modelSettings":{"temperature":0,"reasoningEffort":null},"externalSandbox":{},"future":{"value":9007199254740993}}`)
	roundTrip(t, input, &settings)
	if !settings.Mode.Present || !settings.Mode.Null || settings.Asks.Present {
		t.Fatal("lost null or omission")
	}
	if settings.ModelSettings.Value.Temperature.Value.String() != "0" {
		t.Fatal("lost zero")
	}
	if err := json.Unmarshal([]byte(`{}`), &settings); err != nil {
		t.Fatal(err)
	}
	if settings.Mode.Present || len(settings.Extra) != 0 {
		t.Fatal("old values survived a replacement decode")
	}
	data, err := json.Marshal(SessionInfo{Type: "session_info", Id: "info", Tools: Some(Tools{}), Missing: Some([]string{})})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), `"tools":[]`) || !strings.Contains(string(data), `"missing":[]`) {
		t.Fatal("lost empty lists")
	}
	data, err = json.Marshal(AgentSettings{Mode: Null[string]()})
	if err != nil || string(data) != `{"mode":null}` {
		t.Fatalf("null helper: %s %v", data, err)
	}
}

func TestLargeNumbersAndUnknownFieldsRemainExact(t *testing.T) {
	var record Inference
	input := []byte(`{"type":"inference","id":"request","usage":{"inputTokens":9007199254740993123456789},"cost":{"amount":0.123456789012345678901,"currency":"USD"},"future":{"value":1e1234}}`)
	roundTrip(t, input, &record)
	if record.Usage.Value.InputTokens.Value.String() != "9007199254740993123456789" {
		t.Fatal("rounded integer")
	}
	if record.Cost.Value.Amount.String() != "0.123456789012345678901" {
		t.Fatal("rounded decimal")
	}
}

func TestExtraCannotOverrideSchemaFields(t *testing.T) {
	_, err := json.Marshal(AgentSettings{Extra: map[string]json.RawMessage{"mode": json.RawMessage(`"hidden"`)}})
	if err == nil {
		t.Fatal("accepted a shadowing extra field")
	}
}

func TestNonObjectsAreRejected(t *testing.T) {
	for _, data := range []string{"null", "[]", "42"} {
		var record Session
		if err := json.Unmarshal([]byte(data), &record); err == nil {
			t.Fatalf("accepted %s", data)
		}
	}
}

func TestEveryExampleRecordRoundTripsAndStillValidates(t *testing.T) {
	var paths []string
	err := filepath.WalkDir("../../examples", func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !entry.IsDir() && strings.HasSuffix(path, ".jsonl") {
			paths = append(paths, path)
		}
		return nil
	})
	if err != nil || len(paths) == 0 {
		t.Fatal("missing examples", err)
	}
	for _, path := range paths {
		t.Run(filepath.Base(path), func(t *testing.T) {
			input, err := os.Open(path)
			if err != nil {
				t.Fatal(err)
			}
			defer input.Close()
			var output bytes.Buffer
			scanner := bufio.NewScanner(input)
			scanner.Buffer(make([]byte, 4096), 4*1024*1024)
			for scanner.Scan() {
				var envelope struct {
					Type string `json:"type"`
				}
				if err := json.Unmarshal(scanner.Bytes(), &envelope); err != nil {
					t.Fatal(err)
				}
				var target any
				switch envelope.Type {
				case "session":
					target = &Session{}
				case "session_info":
					target = &SessionInfo{}
				case "message":
					target = &Message{}
				case "tool_call":
					target = &ToolCall{}
				case "tool_result":
					target = &ToolResult{}
				case "approval":
					target = &Approval{}
				case "file_change":
					target = &FileChange{}
				case "vcs":
					target = &VcsRecord{}
				case "inference":
					target = &Inference{}
				case "gap":
					target = &Gap{}
				case "annotation":
					target = &Annotation{}
				default:
					target = &Envelope{}
				}
				output.Write(roundTrip(t, scanner.Bytes(), target))
				output.WriteByte('\n')
			}
			if err := scanner.Err(); err != nil {
				t.Fatal(err)
			}
			resultPath := filepath.Join(t.TempDir(), filepath.Base(path))
			if err := os.WriteFile(resultPath, output.Bytes(), 0600); err != nil {
				t.Fatal(err)
			}
			command := exec.Command("node", "../../tools/validator/bin/asr-validate.js", "--json", "--summary", resultPath)
			data, err := command.CombinedOutput()
			if err != nil {
				t.Fatalf("validation failed: %v %s", err, data)
			}
			var result struct {
				Errors   int `json:"errors"`
				Warnings int `json:"warnings"`
			}
			if err := json.Unmarshal(data, &result); err != nil {
				t.Fatal(err)
			}
			if result.Errors != 0 || result.Warnings != 0 {
				t.Fatalf("unexpected diagnostics: %s", data)
			}
		})
	}
}

func TestCompanionDocumentsRoundTrip(t *testing.T) {
	var manifest Manifest
	data, err := os.ReadFile("../../examples/collection.manifest.json")
	if err != nil {
		t.Fatal(err)
	}
	roundTrip(t, data, &manifest)
	var discovery Discovery
	roundTrip(t, []byte(`{"agent":"com.example.agent","supportsDeletionHook":false,"future":{"number":9007199254740993}}`), &discovery)
	var annotation TitleAnnotation
	roundTrip(t, []byte(`{"type":"annotation","id":"title","session":"com.example.agent:run","kind":"title","at":"2026-10-31T12:00:00Z","source":{"name":"example"},"data":{"title":"Synthetic"}}`), &annotation)
}
