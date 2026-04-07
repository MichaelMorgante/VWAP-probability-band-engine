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
//| VWAP Double Overlay - Phase B                                    |
//| Straight execution lines from live_state.json                    |
//| Bendy context bands + faint fills from live_context.json         |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 13
#property indicator_plots   10

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

// Context line colours
input color ColorCtxRef = clrMediumPurple;
input color ColorCtx1   = clrTurquoise;
input color ColorCtx2   = clrOrchid;
input color ColorCtx3   = clrSlateBlue;

// Context fill colours
input color ColorFill1 = clrPaleTurquoise;
input color ColorFill2 = clrThistle;
input color ColorFill3 = clrLavender;

// Signal colours
input color ColorSignalMR   = clrLimeGreen;
input color ColorSignalCont = clrOrangeRed;

// Buffers
double BufFill1U[];
double BufFill1L[];
double BufFill2U[];
double BufFill2L[];
double BufFill3U[];
double BufFill3L[];
double BufCtxRef[];
double BufCtx1P[];
double BufCtx1N[];
double BufCtx2P[];
double BufCtx2N[];
double BufCtx3P[];
double BufCtx3N[];

// Straight execution state
double g_reference = 0, g_sigma = 0, g_z_score = 0;
string g_zone = "", g_signal_type = "NO_SIGNAL", g_trend = "";
double g_p_mr = 0, g_edge_gap = 0;
double g_band1p = 0, g_band1n = 0;
double g_band2p = 0, g_band2n = 0;
double g_band3p = 0, g_band3n = 0;

// Context arrays from JSON
#define MAX_CTX_POINTS 300
int    g_ctx_count = 0;
double g_ctx_ref[MAX_CTX_POINTS];
double g_ctx_1p[MAX_CTX_POINTS];
double g_ctx_1n[MAX_CTX_POINTS];
double g_ctx_2p[MAX_CTX_POINTS];
double g_ctx_2n[MAX_CTX_POINTS];
double g_ctx_3p[MAX_CTX_POINTS];
double g_ctx_3n[MAX_CTX_POINTS];

//+------------------------------------------------------------------+
int OnInit()
  {
   // Plot 0: Fill 1
   SetIndexBuffer(0, BufFill1U, INDICATOR_DATA);
   SetIndexBuffer(1, BufFill1L, INDICATOR_DATA);

   // Plot 1: Fill 2
   SetIndexBuffer(2, BufFill2U, INDICATOR_DATA);
   SetIndexBuffer(3, BufFill2L, INDICATOR_DATA);

   // Plot 2: Fill 3
   SetIndexBuffer(4, BufFill3U, INDICATOR_DATA);
   SetIndexBuffer(5, BufFill3L, INDICATOR_DATA);

   // Plot 3..9: lines
   SetIndexBuffer(6,  BufCtxRef, INDICATOR_DATA);
   SetIndexBuffer(7,  BufCtx1P,  INDICATOR_DATA);
   SetIndexBuffer(8,  BufCtx1N,  INDICATOR_DATA);
   SetIndexBuffer(9,  BufCtx2P,  INDICATOR_DATA);
   SetIndexBuffer(10, BufCtx2N,  INDICATOR_DATA);
   SetIndexBuffer(11, BufCtx3P,  INDICATOR_DATA);
   SetIndexBuffer(12, BufCtx3N,  INDICATOR_DATA);

   ArraySetAsSeries(BufFill1U, true);
   ArraySetAsSeries(BufFill1L, true);
   ArraySetAsSeries(BufFill2U, true);
   ArraySetAsSeries(BufFill2L, true);
   ArraySetAsSeries(BufFill3U, true);
   ArraySetAsSeries(BufFill3L, true);
   ArraySetAsSeries(BufCtxRef, true);
   ArraySetAsSeries(BufCtx1P, true);
   ArraySetAsSeries(BufCtx1N, true);
   ArraySetAsSeries(BufCtx2P, true);
   ArraySetAsSeries(BufCtx2N, true);
   ArraySetAsSeries(BufCtx3P, true);
   ArraySetAsSeries(BufCtx3N, true);

   // Fill plots
   PlotIndexSetInteger(0, PLOT_DRAW_TYPE, DRAW_FILLING);
   PlotIndexSetInteger(0, PLOT_LINE_COLOR, 0, ColorFill1);
   PlotIndexSetString(0, PLOT_LABEL, "Ctx Fill 1");

   PlotIndexSetInteger(1, PLOT_DRAW_TYPE, DRAW_FILLING);
   PlotIndexSetInteger(1, PLOT_LINE_COLOR, 0, ColorFill2);
   PlotIndexSetString(1, PLOT_LABEL, "Ctx Fill 2");

   PlotIndexSetInteger(2, PLOT_DRAW_TYPE, DRAW_FILLING);
   PlotIndexSetInteger(2, PLOT_LINE_COLOR, 0, ColorFill3);
   PlotIndexSetString(2, PLOT_LABEL, "Ctx Fill 3");

   // Context reference
   PlotIndexSetInteger(3, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(3, PLOT_LINE_COLOR, 0, ColorCtxRef);
   PlotIndexSetInteger(3, PLOT_LINE_WIDTH, 2);
   PlotIndexSetString(3, PLOT_LABEL, "Ctx Ref");

   // ±1
   PlotIndexSetInteger(4, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(4, PLOT_LINE_COLOR, 0, ColorCtx1);
   PlotIndexSetInteger(4, PLOT_LINE_STYLE, STYLE_DOT);
   PlotIndexSetInteger(4, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(4, PLOT_LABEL, "Ctx 1+");

   PlotIndexSetInteger(5, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(5, PLOT_LINE_COLOR, 0, ColorCtx1);
   PlotIndexSetInteger(5, PLOT_LINE_STYLE, STYLE_DOT);
   PlotIndexSetInteger(5, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(5, PLOT_LABEL, "Ctx 1-");

   // ±2
   PlotIndexSetInteger(6, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(6, PLOT_LINE_COLOR, 0, ColorCtx2);
   PlotIndexSetInteger(6, PLOT_LINE_STYLE, STYLE_DASH);
   PlotIndexSetInteger(6, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(6, PLOT_LABEL, "Ctx 2+");

   PlotIndexSetInteger(7, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(7, PLOT_LINE_COLOR, 0, ColorCtx2);
   PlotIndexSetInteger(7, PLOT_LINE_STYLE, STYLE_DASH);
   PlotIndexSetInteger(7, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(7, PLOT_LABEL, "Ctx 2-");

   // ±3
   PlotIndexSetInteger(8, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(8, PLOT_LINE_COLOR, 0, ColorCtx3);
   PlotIndexSetInteger(8, PLOT_LINE_STYLE, STYLE_DASHDOT);
   PlotIndexSetInteger(8, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(8, PLOT_LABEL, "Ctx 3+");

   PlotIndexSetInteger(9, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(9, PLOT_LINE_COLOR, 0, ColorCtx3);
   PlotIndexSetInteger(9, PLOT_LINE_STYLE, STYLE_DASHDOT);
   PlotIndexSetInteger(9, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(9, PLOT_LABEL, "Ctx 3-");

   EventSetTimer(2);
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
   ReadJsonContext();
   DrawExecutionOverlay();
   if(ShowSignalText) DrawSignalText();
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   ReadJsonState();
   ReadJsonContext();

   ClearContextBuffers(rates_total);

   if(ShowContextBands)
      LoadContextIntoBuffers(rates_total);

   DrawExecutionOverlay();

   if(ShowSignalText)
      DrawSignalText();

   return(rates_total);
  }

//+------------------------------------------------------------------+
void ClearContextBuffers(const int rates_total)
  {
   int lim = MathMin(rates_total, MAX_CTX_POINTS + 20);
   for(int i = 0; i < lim; i++)
     {
      BufFill1U[i] = EMPTY_VALUE;
      BufFill1L[i] = EMPTY_VALUE;
      BufFill2U[i] = EMPTY_VALUE;
      BufFill2L[i] = EMPTY_VALUE;
      BufFill3U[i] = EMPTY_VALUE;
      BufFill3L[i] = EMPTY_VALUE;

      BufCtxRef[i] = EMPTY_VALUE;
      BufCtx1P[i]  = EMPTY_VALUE;
      BufCtx1N[i]  = EMPTY_VALUE;
      BufCtx2P[i]  = EMPTY_VALUE;
      BufCtx2N[i]  = EMPTY_VALUE;
      BufCtx3P[i]  = EMPTY_VALUE;
      BufCtx3N[i]  = EMPTY_VALUE;
     }
  }

//+------------------------------------------------------------------+
void LoadContextIntoBuffers(const int rates_total)
  {
   if(g_ctx_count <= 0) return;

   // Python writes only closed bars.
   // So newest exported point belongs on shift 1, not shift 0.
   for(int i = 0; i < g_ctx_count; i++)
     {
      int shift = g_ctx_count - i;
      if(shift >= rates_total) continue;

      BufFill1U[shift] = g_ctx_1p[i];
      BufFill1L[shift] = g_ctx_1n[i];
      BufFill2U[shift] = g_ctx_2p[i];
      BufFill2L[shift] = g_ctx_2n[i];
      BufFill3U[shift] = g_ctx_3p[i];
      BufFill3L[shift] = g_ctx_3n[i];

      BufCtxRef[shift] = g_ctx_ref[i];
      BufCtx1P[shift]  = g_ctx_1p[i];
      BufCtx1N[shift]  = g_ctx_1n[i];
      BufCtx2P[shift]  = g_ctx_2p[i];
      BufCtx2N[shift]  = g_ctx_2n[i];
      BufCtx3P[shift]  = g_ctx_3p[i];
      BufCtx3N[shift]  = g_ctx_3n[i];
     }
  }

//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
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
      int ref_pos = StringFind(content, "\"ctx_ref\":", pos);
      if(ref_pos < 0 || g_ctx_count >= MAX_CTX_POINTS) break;

      g_ctx_ref[g_ctx_count] = ExtractDoubleFrom(content, ref_pos, "ctx_ref");
      g_ctx_1p[g_ctx_count]  = ExtractDoubleFrom(content, ref_pos, "ctx_1p");
      g_ctx_1n[g_ctx_count]  = ExtractDoubleFrom(content, ref_pos, "ctx_1n");
      g_ctx_2p[g_ctx_count]  = ExtractDoubleFrom(content, ref_pos, "ctx_2p");
      g_ctx_2n[g_ctx_count]  = ExtractDoubleFrom(content, ref_pos, "ctx_2n");
      g_ctx_3p[g_ctx_count]  = ExtractDoubleFrom(content, ref_pos, "ctx_3p");
      g_ctx_3n[g_ctx_count]  = ExtractDoubleFrom(content, ref_pos, "ctx_3n");

      g_ctx_count++;
      pos = ref_pos + 1;
     }
  }

//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
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
void DrawExecutionOverlay()
  {
   if(!ShowExecutionBands || g_reference <= 0) return;

   DrawHLine("VWAP_REF", g_reference, ColorVWAP, 2, STYLE_SOLID);
   DrawHLine("VWAP_1P",  g_band1p,    ColorBand1, 1, STYLE_DOT);
   DrawHLine("VWAP_1N",  g_band1n,    ColorBand1, 1, STYLE_DOT);
   DrawHLine("VWAP_2P",  g_band2p,    ColorBand2, 1, STYLE_DASH);
   DrawHLine("VWAP_2N",  g_band2n,    ColorBand2, 1, STYLE_DASH);
   DrawHLine("VWAP_3P",  g_band3p,    ColorBand3, 1, STYLE_DASHDOT);
   DrawHLine("VWAP_3N",  g_band3n,    ColorBand3, 1, STYLE_DASHDOT);
  }

//+------------------------------------------------------------------+
void DrawSignalText()
  {
   string label = StringFormat(
      "Zone: %s | Z: %.2f | Trend: %s\nP(MR): %.0f%%  Edge: %.2f\nSignal: %s",
      g_zone, g_z_score, g_trend,
      g_p_mr * 100.0, g_edge_gap,
      g_signal_type
   );
   Comment(label);
  }
//+------------------------------------------------------------------+
'''
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(mql5_code.strip(), encoding="utf-8")
    return output_path