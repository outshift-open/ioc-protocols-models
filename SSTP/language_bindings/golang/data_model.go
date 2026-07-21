// Copyright 2026 Cisco Systems, Inc. and its affiliates
//
// SPDX-License-Identifier: Apache-2.0

package l9

import "encoding/json"
import "errors"
import "fmt"
import "reflect"

// A participant in a protocol exchange - can be a human, an AI agent, or a system.
// Multiple actors are listed in L9Header.actors to identify sender(s) and
// receiver(s).
type Actor struct {
	// Attestation corresponds to the JSON schema field "attestation".
	Attestation interface{} `json:"attestation,omitempty,omitzero" yaml:"attestation,omitempty" mapstructure:"attestation,omitempty"`

	// ID corresponds to the JSON schema field "id".
	ID string `json:"id" yaml:"id" mapstructure:"id"`

	// Role corresponds to the JSON schema field "role".
	Role string `json:"role" yaml:"role" mapstructure:"role"`
}

type ActorAttestation_0 *string

// UnmarshalJSON implements json.Unmarshaler.
func (j *Actor) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["id"]; raw != nil && !ok {
		return fmt.Errorf("field id in Actor: required")
	}
	if _, ok := raw["role"]; raw != nil && !ok {
		return fmt.Errorf("field role in Actor: required")
	}
	type Plain Actor
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Actor(plain)
	return nil
}

type Context struct {
	// Epistemic corresponds to the JSON schema field "epistemic".
	Epistemic *ContextEpistemic `json:"epistemic,omitempty,omitzero" yaml:"epistemic,omitempty" mapstructure:"epistemic,omitempty"`

	// Semantic corresponds to the JSON schema field "semantic".
	Semantic *ContextSemantic `json:"semantic,omitempty,omitzero" yaml:"semantic,omitempty" mapstructure:"semantic,omitempty"`

	// Topic corresponds to the JSON schema field "topic".
	Topic string `json:"topic" yaml:"topic" mapstructure:"topic"`
}

// Participant epistemic (belief/knowledge) state at the time the message was sent.
// Currently a placeholder — fields will be added as the model is defined.
type ContextEpistemic map[string]interface{}

// Describes the semantic/ontological framework needed to correctly interpret the
// payload.
// The CFN routing layer uses this to select appropriate cognitive engines (CEs).
type ContextSemantic struct {
	// OntologyRef corresponds to the JSON schema field "ontology_ref".
	OntologyRef string `json:"ontology_ref" yaml:"ontology_ref" mapstructure:"ontology_ref"`

	// Provenance corresponds to the JSON schema field "provenance".
	Provenance *ContextSemanticProvenance `json:"provenance,omitempty,omitzero" yaml:"provenance,omitempty" mapstructure:"provenance,omitempty"`

	// SchemaID corresponds to the JSON schema field "schema_id".
	SchemaID string `json:"schema_id" yaml:"schema_id" mapstructure:"schema_id"`
}

// Tracks the origin and lineage of a message - who created it, from what source,
// and through which transformations. Fields TBD.
type ContextSemanticProvenance map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *ContextSemantic) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var contextSemantic_0 ContextSemantic_0
	var errs []error
	if err := contextSemantic_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain ContextSemantic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = ContextSemantic(plain)
	return nil
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Context) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["topic"]; raw != nil && !ok {
		return fmt.Errorf("field topic in Context: required")
	}
	type Plain Context
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Context(plain)
	return nil
}

// A discrete conversation or interaction sequence.
// An episode groups the messages exchanged during one focused interaction
// (e.g. one round of clarification, one tool invocation cycle).
type Episode struct {
	// ID corresponds to the JSON schema field "id".
	ID string `json:"id" yaml:"id" mapstructure:"id"`

	// Messages corresponds to the JSON schema field "messages".
	Messages []Message `json:"messages" yaml:"messages" mapstructure:"messages"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Episode) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["id"]; raw != nil && !ok {
		return fmt.Errorf("field id in Episode: required")
	}
	if _, ok := raw["messages"]; raw != nil && !ok {
		return fmt.Errorf("field messages in Episode: required")
	}
	type Plain Episode
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Episode(plain)
	return nil
}

// Participant epistemic (belief/knowledge) state at the time the message was sent.
// Currently a placeholder — fields will be added as the model is defined.
type Epistemic map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Epistemic) UnmarshalJSON(value []byte) error {
	type Plain Epistemic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Epistemic(plain)
	return nil
}

type Kind string

const KindCommit Kind = "commit"
const KindContingency Kind = "contingency"
const KindExchange Kind = "exchange"
const KindIntent Kind = "intent"
const KindKnowledge Kind = "knowledge"

var enumValues_Kind = []interface{}{
	"intent",
	"contingency",
	"exchange",
	"commit",
	"knowledge",
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Kind) UnmarshalJSON(value []byte) error {
	var v string
	if err := json.Unmarshal(value, &v); err != nil {
		return err
	}
	var ok bool
	for _, expected := range enumValues_Kind {
		if reflect.DeepEqual(v, expected) {
			ok = true
			break
		}
	}
	if !ok {
		return fmt.Errorf("invalid value (expected one of %#v): %#v", enumValues_Kind, v)
	}
	*j = Kind(v)
	return nil
}

// A complete L9 message: header (routing/metadata) + payload (content).
// This is the top-level structure passed between participants in the IoC protocol.
type L9 struct {
	// Header corresponds to the JSON schema field "header".
	Header L9Header `json:"header" yaml:"header" mapstructure:"header"`

	// Payload corresponds to the JSON schema field "payload".
	Payload L9Payload `json:"payload" yaml:"payload" mapstructure:"payload"`
}

// Routing and metadata envelope for every L9 message.
// The routing layer reads the header — especially `kind` and `subkind` —
// to decide which handler should process the message.
//
// In the stateful design, the header carries the complete session history
// including all episodes and messages.
type L9Header struct {
	// Attributes corresponds to the JSON schema field "attributes".
	Attributes *L9HeaderAttributes `json:"attributes,omitempty,omitzero" yaml:"attributes,omitempty" mapstructure:"attributes,omitempty"`

	// Context corresponds to the JSON schema field "context".
	Context *L9HeaderContext `json:"context,omitempty,omitzero" yaml:"context,omitempty" mapstructure:"context,omitempty"`

	// Kind corresponds to the JSON schema field "kind".
	Kind Kind `json:"kind" yaml:"kind" mapstructure:"kind"`

	// Participants corresponds to the JSON schema field "participants".
	Participants ParticipantSet `json:"participants" yaml:"participants" mapstructure:"participants"`

	// Policy corresponds to the JSON schema field "policy".
	Policy *L9HeaderPolicy `json:"policy,omitempty,omitzero" yaml:"policy,omitempty" mapstructure:"policy,omitempty"`

	// Protocol corresponds to the JSON schema field "protocol".
	Protocol string `json:"protocol" yaml:"protocol" mapstructure:"protocol"`

	// Session corresponds to the JSON schema field "session".
	Session Session `json:"session" yaml:"session" mapstructure:"session"`

	// Subkind corresponds to the JSON schema field "subkind".
	Subkind interface{} `json:"subkind,omitempty,omitzero" yaml:"subkind,omitempty" mapstructure:"subkind,omitempty"`

	// Subprotocol corresponds to the JSON schema field "subprotocol".
	Subprotocol string `json:"subprotocol" yaml:"subprotocol" mapstructure:"subprotocol"`

	// Version corresponds to the JSON schema field "version".
	Version string `json:"version" yaml:"version" mapstructure:"version"`
}

type L9HeaderAttributes map[string]interface{}

type L9HeaderAttributes_0 map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderAttributes_0) UnmarshalJSON(value []byte) error {
	type Plain L9HeaderAttributes_0
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderAttributes_0(plain)
	return nil
}

type L9HeaderContext struct {
	// Epistemic corresponds to the JSON schema field "epistemic".
	Epistemic *L9HeaderContextEpistemic `json:"epistemic,omitempty,omitzero" yaml:"epistemic,omitempty" mapstructure:"epistemic,omitempty"`

	// Semantic corresponds to the JSON schema field "semantic".
	Semantic *L9HeaderContextSemantic `json:"semantic,omitempty,omitzero" yaml:"semantic,omitempty" mapstructure:"semantic,omitempty"`

	// Topic corresponds to the JSON schema field "topic".
	Topic string `json:"topic" yaml:"topic" mapstructure:"topic"`
}

// Participant epistemic (belief/knowledge) state at the time the message was sent.
// Currently a placeholder — fields will be added as the model is defined.
type L9HeaderContextEpistemic map[string]interface{}

// Describes the semantic/ontological framework needed to correctly interpret the
// payload.
// The CFN routing layer uses this to select appropriate cognitive engines (CEs).
type L9HeaderContextSemantic struct {
	// OntologyRef corresponds to the JSON schema field "ontology_ref".
	OntologyRef string `json:"ontology_ref" yaml:"ontology_ref" mapstructure:"ontology_ref"`

	// Provenance corresponds to the JSON schema field "provenance".
	Provenance *L9HeaderContextSemanticProvenance `json:"provenance,omitempty,omitzero" yaml:"provenance,omitempty" mapstructure:"provenance,omitempty"`

	// SchemaID corresponds to the JSON schema field "schema_id".
	SchemaID string `json:"schema_id" yaml:"schema_id" mapstructure:"schema_id"`
}

// Tracks the origin and lineage of a message - who created it, from what source,
// and through which transformations. Fields TBD.
type L9HeaderContextSemanticProvenance map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderContextSemantic) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var l9HeaderContextSemantic_0 L9HeaderContextSemantic_0
	var errs []error
	if err := l9HeaderContextSemantic_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain L9HeaderContextSemantic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderContextSemantic(plain)
	return nil
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderContext) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var l9HeaderContext_0 L9HeaderContext_0
	var errs []error
	if err := l9HeaderContext_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain L9HeaderContext
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderContext(plain)
	return nil
}

// Data governance and access-control labels applied to the message.
type L9HeaderPolicy struct {
	// Propagation corresponds to the JSON schema field "propagation".
	Propagation string `json:"propagation" yaml:"propagation" mapstructure:"propagation"`

	// RetentionPolicy corresponds to the JSON schema field "retention_policy".
	RetentionPolicy string `json:"retention_policy" yaml:"retention_policy" mapstructure:"retention_policy"`

	// Sensitivity corresponds to the JSON schema field "sensitivity".
	Sensitivity string `json:"sensitivity" yaml:"sensitivity" mapstructure:"sensitivity"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderPolicy) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var l9HeaderPolicy_0 L9HeaderPolicy_0
	var errs []error
	if err := l9HeaderPolicy_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain L9HeaderPolicy
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderPolicy(plain)
	return nil
}

type L9HeaderSubkind_0 *string

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9Header) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["kind"]; raw != nil && !ok {
		return fmt.Errorf("field kind in L9Header: required")
	}
	if _, ok := raw["participants"]; raw != nil && !ok {
		return fmt.Errorf("field participants in L9Header: required")
	}
	if _, ok := raw["protocol"]; raw != nil && !ok {
		return fmt.Errorf("field protocol in L9Header: required")
	}
	if _, ok := raw["session"]; raw != nil && !ok {
		return fmt.Errorf("field session in L9Header: required")
	}
	if _, ok := raw["subprotocol"]; raw != nil && !ok {
		return fmt.Errorf("field subprotocol in L9Header: required")
	}
	if _, ok := raw["version"]; raw != nil && !ok {
		return fmt.Errorf("field version in L9Header: required")
	}
	type Plain L9Header
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9Header(plain)
	return nil
}

// The actual content being carried by an L9 message.
// The `type` field describes the payload format; `data` holds the content.
type L9Payload struct {
	// Data corresponds to the JSON schema field "data".
	Data L9PayloadData `json:"data" yaml:"data" mapstructure:"data"`

	// Type corresponds to the JSON schema field "type".
	Type string `json:"type" yaml:"type" mapstructure:"type"`
}

type L9PayloadData map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9Payload) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["data"]; raw != nil && !ok {
		return fmt.Errorf("field data in L9Payload: required")
	}
	if _, ok := raw["type"]; raw != nil && !ok {
		return fmt.Errorf("field type in L9Payload: required")
	}
	type Plain L9Payload
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9Payload(plain)
	return nil
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["header"]; raw != nil && !ok {
		return fmt.Errorf("field header in L9: required")
	}
	if _, ok := raw["payload"]; raw != nil && !ok {
		return fmt.Errorf("field payload in L9: required")
	}
	type Plain L9
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9(plain)
	return nil
}

// Represents a single message in the protocol.
// In the stateful design, messages are embedded within episodes,
// so we only need the message ID here.
type Message struct {
	// ID corresponds to the JSON schema field "id".
	ID string `json:"id" yaml:"id" mapstructure:"id"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Message) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["id"]; raw != nil && !ok {
		return fmt.Errorf("field id in Message: required")
	}
	type Plain Message
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Message(plain)
	return nil
}

type ParticipantSet struct {
	// Actors corresponds to the JSON schema field "actors".
	Actors []Actor `json:"actors" yaml:"actors" mapstructure:"actors"`

	// Groups corresponds to the JSON schema field "groups".
	Groups *ParticipantSetGroups `json:"groups" yaml:"groups" mapstructure:"groups"`
}

type ParticipantSetGroups map[string]interface{}

type ParticipantSetGroups_0 map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *ParticipantSetGroups_0) UnmarshalJSON(value []byte) error {
	type Plain ParticipantSetGroups_0
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = ParticipantSetGroups_0(plain)
	return nil
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *ParticipantSet) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["actors"]; raw != nil && !ok {
		return fmt.Errorf("field actors in ParticipantSet: required")
	}
	if _, ok := raw["groups"]; raw != nil && !ok {
		return fmt.Errorf("field groups in ParticipantSet: required")
	}
	type Plain ParticipantSet
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = ParticipantSet(plain)
	return nil
}

// Data governance and access-control labels applied to the message.
type PolicyLabel struct {
	// Propagation corresponds to the JSON schema field "propagation".
	Propagation string `json:"propagation" yaml:"propagation" mapstructure:"propagation"`

	// RetentionPolicy corresponds to the JSON schema field "retention_policy".
	RetentionPolicy string `json:"retention_policy" yaml:"retention_policy" mapstructure:"retention_policy"`

	// Sensitivity corresponds to the JSON schema field "sensitivity".
	Sensitivity string `json:"sensitivity" yaml:"sensitivity" mapstructure:"sensitivity"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *PolicyLabel) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["propagation"]; raw != nil && !ok {
		return fmt.Errorf("field propagation in PolicyLabel: required")
	}
	if _, ok := raw["retention_policy"]; raw != nil && !ok {
		return fmt.Errorf("field retention_policy in PolicyLabel: required")
	}
	if _, ok := raw["sensitivity"]; raw != nil && !ok {
		return fmt.Errorf("field sensitivity in PolicyLabel: required")
	}
	type Plain PolicyLabel
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = PolicyLabel(plain)
	return nil
}

// Tracks the origin and lineage of a message - who created it, from what source,
// and through which transformations. Fields TBD.
type Provenance map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Provenance) UnmarshalJSON(value []byte) error {
	type Plain Provenance
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Provenance(plain)
	return nil
}

// Describes the semantic/ontological framework needed to correctly interpret the
// payload.
// The CFN routing layer uses this to select appropriate cognitive engines (CEs).
type Semantic struct {
	// OntologyRef corresponds to the JSON schema field "ontology_ref".
	OntologyRef string `json:"ontology_ref" yaml:"ontology_ref" mapstructure:"ontology_ref"`

	// Provenance corresponds to the JSON schema field "provenance".
	Provenance *SemanticProvenance `json:"provenance,omitempty,omitzero" yaml:"provenance,omitempty" mapstructure:"provenance,omitempty"`

	// SchemaID corresponds to the JSON schema field "schema_id".
	SchemaID string `json:"schema_id" yaml:"schema_id" mapstructure:"schema_id"`
}

// Tracks the origin and lineage of a message - who created it, from what source,
// and through which transformations. Fields TBD.
type SemanticProvenance map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Semantic) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["ontology_ref"]; raw != nil && !ok {
		return fmt.Errorf("field ontology_ref in Semantic: required")
	}
	if _, ok := raw["schema_id"]; raw != nil && !ok {
		return fmt.Errorf("field schema_id in Semantic: required")
	}
	type Plain Semantic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Semantic(plain)
	return nil
}

// A complete session containing all episodes and messages.
// Each L9 message carries the full session state, providing complete history.
type Session struct {
	// Episodes corresponds to the JSON schema field "episodes".
	Episodes []Episode `json:"episodes" yaml:"episodes" mapstructure:"episodes"`

	// ID corresponds to the JSON schema field "id".
	ID string `json:"id" yaml:"id" mapstructure:"id"`
}

type ContextEpistemic_0 = Epistemic

type ContextSemantic_0 = Semantic

type SemanticProvenance_0 = Provenance

// UnmarshalJSON implements json.Unmarshaler.
func (j *Session) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["episodes"]; raw != nil && !ok {
		return fmt.Errorf("field episodes in Session: required")
	}
	if _, ok := raw["id"]; raw != nil && !ok {
		return fmt.Errorf("field id in Session: required")
	}
	type Plain Session
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Session(plain)
	return nil
}

type L9HeaderPolicy_0 = PolicyLabel

type L9HeaderContextSemanticProvenance_0 = Provenance

type L9HeaderContextEpistemic_0 = Epistemic

type L9HeaderContext_0 = Context

type ContextSemanticProvenance_0 = Provenance

type L9HeaderContextSemantic_0 = Semantic
