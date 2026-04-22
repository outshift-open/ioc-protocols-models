# SSTP Go Bindings

Go module (`github.com/cisco-outshift/ioc-cfn/sstp`) providing L9 header types for the **Structured Semantic Transport Protocol (SSTP)**.

## Generate

Go types are generated from the canonical JSON schema using [go-jsonschema](https://github.com/atombender/go-jsonschema):

```bash
./generate.sh
```

This installs `go-jsonschema` if absent, reads `SSTP/JSON schema/sstp-schema.json`, and writes `sstp/l9_types.go`.

## Run tests

```bash
go test ./tests/...
```

## Module layout

```
sstp/
  l9.go        # Transport, Kind constants, Header struct, MessageID helper
  l9_types.go  # Generated structs (produced by generate.sh)
tests/
  l9_test.go   # Validation tests
generate.sh    # Code-generation driver
go.mod
```

## Import

```go
import "github.com/cisco-outshift/ioc-cfn/sstp/sstp"

id := sstp.MessageID("agent-1", time.Now().UnixMilli())
h := sstp.Header{
    Protocol:  sstp.TransportSSTP,
    Version:   sstp.Version,
    Kind:      sstp.KindIntent,
    MessageID: id,
    // ...
}
```

See `../../spec/SSTP_FORMAL_MODEL.md` for the normative field definitions.
