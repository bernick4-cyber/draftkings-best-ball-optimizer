# 3-Year Fantasy Draft Strategy Analyzer

Streamlit app using 2023–2025 fantasy draft/performance data.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Main outputs
- Best position by draft round
- Round x position heatmap
- Hit rate, PPG, boom rates, and composite value score
- Year-by-year validation
- Player drilldown behind each recommendation

Values above round 19 in the source workbook are grouped into `20+` so late/undrafted values do not display as impossible draft rounds.
