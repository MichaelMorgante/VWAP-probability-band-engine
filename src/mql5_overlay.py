from pathlib import Path
import os
import glob
import shutil


def write_mql5_overlay(output_dir: str = "live_artifacts",
                       filename: str = "VWAP_Overlay.mq5") -> None:
    """
    Generate the MQL5 overlay source file and attempt to copy it
    into the local MT5 Indicators directory.
    """
    mql5_code = r'''
//+------------------------------------------------------------------+
//| VWAP Probability Band Overlay                                     |
//| Reads live_state.json from Python engine once per bar             |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0

// JSON file path — must match output_path in run_live()
input string JsonPath = "live_state.json";

// Display toggles
input bool ShowBands   = true;
input bool ShowSignal  = true;
input bool ShowZScore  = true;

// Band colours
input color ColorVWAP  = clrDodgerBlue;
input color ColorBand1 = clrLimeGreen;
input color ColorBand2 = clrOrange;
input color ColorBand3 = clrRed;
input color ColorSignalMR   = clrLimeGreen;
input color ColorSignalCont = clrOrangeRed;

// Internal state
double g_reference = 0, g_sigma = 0, g_z_score = 0;
string g_zone = "", g_signal_type = "NO_SIGNAL", g_trend = "";
double g_p_mr = 0, g_edge_gap = 0;
double g_band1p = 0, g_band1n = 0;
double g_band2p = 0, g_band2n = 0;
double g_band3p = 0, g_band3n = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(5); // poll JSON every 5 seconds
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0, "VWAP_");
   Comment("");
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   ReadJsonState();
   DrawOverlay();
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   ReadJsonState();
   DrawOverlay();
   return(rates_total);
  }

//+------------------------------------------------------------------+
void ReadJsonState()
  {
   int handle = FileOpen(JsonPath, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE) return;

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

   // Simple key-value extraction (no full JSON parser needed)
   g_reference   = ExtractDouble(content, "reference");
   g_sigma       = ExtractDouble(content, "sigma");
   g_z_score     = ExtractDouble(content, "z_score");
   g_p_mr        = ExtractDouble(content, "p_mr");
   g_edge_gap    = ExtractDouble(content, "edge_gap");
   g_band1p      = ExtractDouble(content, "band_1p");
   g_band1n      = ExtractDouble(content, "band_1n");
   g_band2p      = ExtractDouble(content, "band_2p");
   g_band2n      = ExtractDouble(content, "band_2n");
   g_band3p      = ExtractDouble(content, "band_3p");
   g_band3n      = ExtractDouble(content, "band_3n");
   g_zone        = ExtractString(content, "zone");
   g_signal_type = ExtractString(content, "signal_type");
   g_trend       = ExtractString(content, "trend_bin");
  }

//+------------------------------------------------------------------+
double ExtractDouble(string json, string key)
  {
   string search = "\"" + key + "\": ";
   int pos = StringFind(json, search);
   if(pos < 0) return 0.0;
   pos += StringLen(search);
   string sub = StringSubstr(json, pos, 20);
   return StringToDouble(sub);
  }

//+------------------------------------------------------------------+
string ExtractString(string json, string key)
  {
   string search = "\"" + key + "\": \"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   int end = StringFind(json, "\"", pos);
   if(end < 0) return "";
   return StringSubstr(json, pos, end - pos);
  }

//+------------------------------------------------------------------+
void DrawHLine(string name, double price, color clr, int width, int style)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
  }

//+------------------------------------------------------------------+
void DrawOverlay()
  {
   if(ShowBands && g_reference > 0)
     {
      DrawHLine("VWAP_REF",   g_reference, ColorVWAP,  2, STYLE_SOLID);
      DrawHLine("VWAP_1P",    g_band1p,    ColorBand1, 1, STYLE_DOT);
      DrawHLine("VWAP_1N",    g_band1n,    ColorBand1, 1, STYLE_DOT);
      DrawHLine("VWAP_2P",    g_band2p,    ColorBand2, 1, STYLE_DASH);
      DrawHLine("VWAP_2N",    g_band2n,    ColorBand2, 1, STYLE_DASH);
      DrawHLine("VWAP_3P",    g_band3p,    ColorBand3, 1, STYLE_DASHDOT);
      DrawHLine("VWAP_3N",    g_band3n,    ColorBand3, 1, STYLE_DASHDOT);
     }

   if(ShowSignal || ShowZScore)
     {
      color sig_color = (g_signal_type == "NO_SIGNAL") ? clrGray :
                        (StringFind(g_signal_type, "MR") >= 0) ? ColorSignalMR : ColorSignalCont;

      string label = StringFormat(
         "Zone: %s | Z: %.2f | Trend: %s\nP(MR): %.0f%%  Edge: %.2f\nSignal: %s",
         g_zone, g_z_score, g_trend,
         g_p_mr * 100, g_edge_gap,
         g_signal_type
      );
      Comment(label);
     }
  }
//+------------------------------------------------------------------+
'''

    local_path = Path(output_dir) / filename
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(mql5_code.strip(), encoding="utf-8")
    print(f"✅ MQL5 source written → {local_path}")

    def find_mt5_indicators_dir():
        appdata = os.environ.get('APPDATA', '')
        candidates = glob.glob(os.path.join(appdata, 'MetaQuotes', 'Terminal', '*', 'MQL5', 'Indicators'))
        if candidates:
            return candidates[0]
        for base in [r'C:/Program Files/MetaTrader 5', r'C:/Program Files (x86)/MetaTrader 5']:
            p = os.path.join(base, 'MQL5', 'Indicators')
            if os.path.isdir(p):
                return p
        return None

    mt5_ind_dir = find_mt5_indicators_dir()

    if mt5_ind_dir:
        dest = Path(mt5_ind_dir) / filename
        shutil.copy2(local_path, dest)
        print(f"✅ Copied to MT5 Indicators → {dest}")
        print(f"   File size: {dest.stat().st_size:,} bytes")
        print()
        print("Next steps:")
        print("  1. In MT5 → Navigator → Indicators → right-click → Refresh")
        print("  2. Double-click VWAP_Overlay to open in MetaEditor")
        print("  3. Press F7 to compile — should show 0 errors")
        print("  4. Compile and attach to your chart")
        print("  5. Run the live engine in the notebook")
    else:
        print("⚠️  MT5 Indicators folder not found automatically.")
        print(f"   Manually copy {local_path.resolve()} to your MT5 MQL5/Indicators/ folder.")
        print("   Then compile in MetaEditor (F7) and attach to chart.")