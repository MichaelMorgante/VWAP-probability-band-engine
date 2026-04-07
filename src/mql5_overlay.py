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


# ── Context overlay: write MT5 double-overlay indicator source ──────

def write_mql5_double_overlay(output_path: str = "live_artifacts/VWAP_Overlay.mq5") -> Path:
    mql5_code = r'''
//+------------------------------------------------------------------+
//| VWAP Double Overlay                                              |
//| Reads live_state.json + live_context.json                        |
//| Straight execution lines + bendy context trail                   |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0

input string JsonPathState   = "live_state.json";
input string JsonPathContext = "live_context.json";

input bool ShowExecutionBands = true;
input bool ShowContextBands   = true;
input bool ShowSignalText     = true;

// Execution colours
input color ColorVWAP  = clrDodgerBlue;
input color ColorBand1 = clrLimeGreen;
input color ColorBand2 = clrOrange;
input color ColorBand3 = clrRed;

// Context colours
input color ColorCtxRef = clrMediumPurple;
input color ColorCtx1   = clrTurquoise;
input color ColorCtx2   = clrOrchid;
input color ColorCtx3   = clrSlateBlue;

// Signal colours
input color ColorSignalMR   = clrLimeGreen;
input color ColorSignalCont = clrOrangeRed;

// Straight execution state
double g_reference = 0, g_sigma = 0, g_z_score = 0;
string g_zone = "", g_signal_type = "NO_SIGNAL", g_trend = "";
double g_p_mr = 0, g_edge_gap = 0;
double g_band1p = 0, g_band1n = 0;
double g_band2p = 0, g_band2n = 0;
double g_band3p = 0, g_band3n = 0;

// Context arrays
#define MAX_CTX_POINTS 100
int      g_ctx_count = 0;
datetime g_ctx_time[MAX_CTX_POINTS];
double   g_ctx_ref[MAX_CTX_POINTS];
double   g_ctx_1p[MAX_CTX_POINTS];
double   g_ctx_1n[MAX_CTX_POINTS];
double   g_ctx_2p[MAX_CTX_POINTS];
double   g_ctx_2n[MAX_CTX_POINTS];
double   g_ctx_3p[MAX_CTX_POINTS];
double   g_ctx_3n[MAX_CTX_POINTS];

int OnInit()
  {
   EventSetTimer(5);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0, "VWAP_");
   ObjectsDeleteAll(0, "CTX_");
   Comment("");
  }

void OnTimer()
  {
   ReadJsonState();
   ReadJsonContext();
   DrawOverlay();
  }

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   ReadJsonState();
   ReadJsonContext();
   DrawOverlay();
   return(rates_total);
  }

void ReadJsonState()
  {
   int handle = FileOpen(JsonPathState, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE) return;

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

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

void ReadJsonContext()
  {
   g_ctx_count = 0;

   int handle = FileOpen(JsonPathContext, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE) return;

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

   int pos = 0;
   while(true)
     {
      int dt_pos = StringFind(content, "\"datetime\":", pos);
      if(dt_pos < 0 || g_ctx_count >= MAX_CTX_POINTS) break;

      string dt_str = ExtractStringFrom(content, dt_pos, "datetime");
      if(dt_str == "")
        {
         pos = dt_pos + 1;
         continue;
        }

      g_ctx_time[g_ctx_count] = StringToTime(dt_str);
      g_ctx_ref[g_ctx_count]  = ExtractDoubleFrom(content, dt_pos, "ctx_ref");
      g_ctx_1p[g_ctx_count]   = ExtractDoubleFrom(content, dt_pos, "ctx_1p");
      g_ctx_1n[g_ctx_count]   = ExtractDoubleFrom(content, dt_pos, "ctx_1n");
      g_ctx_2p[g_ctx_count]   = ExtractDoubleFrom(content, dt_pos, "ctx_2p");
      g_ctx_2n[g_ctx_count]   = ExtractDoubleFrom(content, dt_pos, "ctx_2n");
      g_ctx_3p[g_ctx_count]   = ExtractDoubleFrom(content, dt_pos, "ctx_3p");
      g_ctx_3n[g_ctx_count]   = ExtractDoubleFrom(content, dt_pos, "ctx_3n");

      g_ctx_count++;
      pos = dt_pos + 1;
     }
  }

double ExtractDouble(string json, string key)
  {
   string search = "\"" + key + "\": ";
   int pos = StringFind(json, search);
   if(pos < 0) return 0.0;
   pos += StringLen(search);

   int end = pos;
   int max_len = StringLen(json);
   while(end < max_len)
     {
      ushort ch = StringGetCharacter(json, end);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '+'
         || ch == 'e' || ch == 'E')
         end++;
      else
         break;
     }

   return StringToDouble(StringSubstr(json, pos, end - pos));
  }

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

double ExtractDoubleFrom(string json, int start_pos, string key)
  {
   string search = "\"" + key + "\": ";
   int pos = StringFind(json, search, start_pos);
   if(pos < 0) return 0.0;
   pos += StringLen(search);

   int end = pos;
   int max_len = StringLen(json);
   while(end < max_len)
     {
      ushort ch = StringGetCharacter(json, end);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '+'
         || ch == 'e' || ch == 'E')
         end++;
      else
         break;
     }

   return StringToDouble(StringSubstr(json, pos, end - pos));
  }

string ExtractStringFrom(string json, int start_pos, string key)
  {
   string search = "\"" + key + "\": \"";
   int pos = StringFind(json, search, start_pos);
   if(pos < 0) return "";
   pos += StringLen(search);
   int end = StringFind(json, "\"", pos);
   if(end < 0) return "";
   return StringSubstr(json, pos, end - pos);
  }

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

void DrawTrendSegment(string name, datetime t1, double p1, datetime t2, double p2,
                      color clr, int width, int style)
  {
   if(t1 <= 0 || t2 <= 0 || p1 == 0 || p2 == 0) return;

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   else
     {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
     }

   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
  }

void DrawContextTrail(string prefix, double &arr[], color clr, int width, int style)
  {
   for(int i = 0; i < g_ctx_count - 1; i++)
     {
      string name = prefix + IntegerToString(i);
      DrawTrendSegment(name,
                       g_ctx_time[i],   arr[i],
                       g_ctx_time[i+1], arr[i+1],
                       clr, width, style);
     }

   for(int j = g_ctx_count - 1; j < MAX_CTX_POINTS; j++)
     {
      string old_name = prefix + IntegerToString(j);
      if(ObjectFind(0, old_name) >= 0)
         ObjectDelete(0, old_name);
     }
  }

void DrawOverlay()
  {
   if(ShowExecutionBands && g_reference > 0)
     {
      DrawHLine("VWAP_REF", g_reference, ColorVWAP, 2, STYLE_SOLID);
      DrawHLine("VWAP_1P",  g_band1p,    ColorBand1, 1, STYLE_DOT);
      DrawHLine("VWAP_1N",  g_band1n,    ColorBand1, 1, STYLE_DOT);
      DrawHLine("VWAP_2P",  g_band2p,    ColorBand2, 1, STYLE_DASH);
      DrawHLine("VWAP_2N",  g_band2n,    ColorBand2, 1, STYLE_DASH);
      DrawHLine("VWAP_3P",  g_band3p,    ColorBand3, 1, STYLE_DASHDOT);
      DrawHLine("VWAP_3N",  g_band3n,    ColorBand3, 1, STYLE_DASHDOT);
     }

   if(ShowContextBands && g_ctx_count > 1)
     {
      DrawContextTrail("CTX_REF_", g_ctx_ref, ColorCtxRef, 2, STYLE_SOLID);
      DrawContextTrail("CTX_1P_",  g_ctx_1p,  ColorCtx1,   1, STYLE_DOT);
      DrawContextTrail("CTX_1N_",  g_ctx_1n,  ColorCtx1,   1, STYLE_DOT);
      DrawContextTrail("CTX_2P_",  g_ctx_2p,  ColorCtx2,   1, STYLE_DASH);
      DrawContextTrail("CTX_2N_",  g_ctx_2n,  ColorCtx2,   1, STYLE_DASH);
      DrawContextTrail("CTX_3P_",  g_ctx_3p,  ColorCtx3,   1, STYLE_DASHDOT);
      DrawContextTrail("CTX_3N_",  g_ctx_3n,  ColorCtx3,   1, STYLE_DASHDOT);
     }

   if(ShowSignalText)
     {
      string label = StringFormat(
         "Zone: %s | Z: %.2f | Trend: %s\nP(MR): %.0f%%  Edge: %.2f\nSignal: %s",
         g_zone, g_z_score, g_trend,
         g_p_mr * 100.0, g_edge_gap,
         g_signal_type
      );
      Comment(label);
     }
  }
//+------------------------------------------------------------------+
'''
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(mql5_code.strip(), encoding="utf-8")
    return output_path


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


def copy_mql5_overlay_to_mt5(source_path: Path) -> Path | None:
    mt5_ind_dir = find_mt5_indicators_dir()
    if not mt5_ind_dir:
        return None

    dest = Path(mt5_ind_dir) / source_path.name
    shutil.copy2(source_path, dest)
    return dest