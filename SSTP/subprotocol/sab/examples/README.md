# SAB — Examples

Example SAB message dumps for the **Quick Deal** mission — two parties
negotiating price and delivery speed for an urgent supply order.

## Files

| File | Description |
|------|-------------|
| `quick_deal_agreement.json` | 6 messages — converged after 2 counter-offers (4 negotiate rounds) |
| `quick_deal_disagreement.json` | 8 messages — step budget (6 rounds) exhausted, no agreement |

Each file is a JSON array of SAB messages, where every message has a `header`
and a `payload`.

## Regenerating

```bash
python3 SSTP/subprotocol/sab/examples/run_demo.py
```

`run_demo.py` builds the message sequences using the SAB Python Pydantic
bindings and overwrites both JSON files in place.
