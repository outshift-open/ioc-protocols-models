// Copyright 2026 Cisco Systems, Inc. and its affiliates
//
// SPDX-License-Identifier: Apache-2.0

package tests

import (
	"testing"

	"github.com/cisco-outshift/ioc-cfn/sstp/sstp"
)

func TestTransportConstants(t *testing.T) {
	cases := []struct {
		got  sstp.Transport
		want string
	}{
		{sstp.TransportSSTP, "SSTP"},
		{sstp.TransportCSTP, "CSTP"},
		{sstp.TransportLSTP, "LSTP"},
	}
	for _, c := range cases {
		if string(c.got) != c.want {
			t.Errorf("transport %q: got %q, want %q", c.want, c.got, c.want)
		}
	}
}

func TestKindConstants(t *testing.T) {
	kinds := []sstp.Kind{
		sstp.KindIntent, sstp.KindDelegation, sstp.KindKnowledge,
		sstp.KindQuery, sstp.KindCommit, sstp.KindMemoryDelta,
		sstp.KindEvidenceBundle, sstp.KindNegotiate,
	}
	for _, k := range kinds {
		if string(k) == "" {
			t.Errorf("kind constant is empty string")
		}
	}
}

func TestMessageIDIsDeterministic(t *testing.T) {
	id1 := sstp.MessageID("agent-1", 1234567890000)
	id2 := sstp.MessageID("agent-1", 1234567890000)
	if id1 != id2 {
		t.Errorf("MessageID not deterministic: %q != %q", id1, id2)
	}
}

func TestMessageIDVariesBySender(t *testing.T) {
	id1 := sstp.MessageID("agent-1", 1000)
	id2 := sstp.MessageID("agent-2", 1000)
	if id1 == id2 {
		t.Error("MessageID should differ for different senders")
	}
}

func TestVersion(t *testing.T) {
	if sstp.Version != "0" {
		t.Errorf("expected Version=0, got %q", sstp.Version)
	}
}
