# AGENTS.md — logo-pack

1. Run from the repo root:
   ```bash
   python logo_pack.py <logo.svg> --mono "<brand hex>" --title "<Brand>" --out-dir <dir>
   ```
   Add `--favicon-source <simpler.svg>` when a simplified small mark exists, `--icon-bg "<hex>"` for the app-icon tile.
2. Open `<dir>/<name>-sheet.svg` (browser or screenshot tool) and look at it. Check:
   - the black, white and mono versions still show every part of the mark (no solid blob);
   - the favicon is recognisable at 16 px on light and dark;
   - the app icon mark is centred and not too small.
3. If the run printed `note: master contains white paint`, or a one-colour version turned into a blob, the master uses white paint as fake cut-outs. Redraw those parts as real holes (one path with `fill-rule="evenodd"`, or subtract the shape) and run again.
4. Report the files written and what the sheet showed. Do not call the logo done while step 2 fails.
