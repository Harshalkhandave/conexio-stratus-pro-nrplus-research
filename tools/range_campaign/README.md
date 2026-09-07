# Range campaign runner

## Same PC (both COM ports on one computer)

```text
python range_campaign.py --tx COM5 --rx COM6 --matrix matrix.yaml
```

## Different PCs (TX board on PC-A, RX board on PC-B)

Copy `tools/range_campaign` + the same `matrix.yaml` to both PCs (or use a shared folder / git pull).

Pick one session name, e.g. `run1`.

### Order for each test

**On RX PC first:**

```text
python range_rx.py --port COMx --matrix matrix.yaml --all --session run1
```

When prompted:
1. Confirm boards are placed → script starts RX listen  
2. Go start TX on the other PC  
3. When TX is done, confirm on RX → script stops RX and saves SUMMARY  

**On TX PC (after RX is listening):**

```text
python range_tx.py --port COMy --matrix matrix.yaml --all --session run1
```

When prompted: confirm placement **and** that RX is already listening → script runs TX count and saves SUMMARY.

### Merge results (on either PC)

Copy both `tx_results.csv` and `rx_results.csv` into the same `data/02_range/run1/` folder, then:

```text
python merge_results.py ../../data/02_range/run1
```

That writes `results.csv` with PDR.

## Tips

- Close other serial terminals on each PC’s COM port  
- Use identical `matrix.yaml` and `--session` on both sides  
- Your role is only placement + the confirm prompts  
