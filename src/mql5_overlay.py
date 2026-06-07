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
input bool ShowBandTable = true;

// Table placement / styling
input int  TableCorner    = CORNER_RIGHT_UPPER;
input int  TableXOffset   = 205;
input int  TableYOffset   = 22;
input int  TableRowGap    = 16;
input int  TableFontSize  = 10;
input color TableTextColor = clrWhite;

// Band colours
input color ColorVWAP  = clrDodgerBlue;
input color ColorBand1 = clrLimeGreen;
input color ColorBand2 = clrOrange;
input color ColorBand3 = clrRed;
input color ColorSignalMR   = clrLimeGreen;
input color ColorSignalCont = clrOrangeRed;
input color ColorMoveUp   = clrLimeGreen;
input color ColorMoveDown = clrTomato;
input color ColorMoveFlat = clrSilver;

// Candle countdown
input bool ShowCandleCountdown = true;
input int CountdownWarningSeconds = 10;
input color ColorCountdownNormal = clrWhite;
input color ColorCountdownWarning = clrRed;

// Session open anchors
input bool AutoSessionDST = true;
input int BrokerUTCOffsetWinter = 2;
input int BrokerUTCOffsetSummer = 3;

// Manual fallback, using broker/server time
input int ManualLondonOpenHour = 10;
input int ManualLondonOpenMinute = 0;
input int ManualNewYorkOpenHour = 16;
input int ManualNewYorkOpenMinute = 30;

// Internal state
double g_reference = 0, g_sigma = 0, g_z_score = 0;
double g_reference_shift_5 = 0;
string g_zone = "", g_signal_type = "NO_SIGNAL", g_trend = "";
string g_trend_display = "FLAT", g_bias_display = "NEUTRAL";
string g_setup_type = "NEUTRAL", g_signal_display = "WAIT", g_suppressed_by = "";
double g_p_mr = 0, g_edge_gap = 0;
double g_band1p = 0, g_band1n = 0;
double g_band2p = 0, g_band2n = 0;
double g_band3p = 0, g_band3n = 0;

// previous values
double g_prev_reference = 0;
double g_prev_band1p = 0, g_prev_band1n = 0;
double g_prev_band2p = 0, g_prev_band2n = 0;
double g_prev_band3p = 0, g_prev_band3n = 0;

// session-open anchors are calculated from London/NY session times

//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(1); // poll JSON every 5 seconds
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

   // read new values into temporaries first
   double new_reference = ExtractDouble(content, "reference");
   double new_reference_shift_5 = ExtractDouble(content, "reference_shift_5");
   double new_sigma     = ExtractDouble(content, "sigma");
   double new_z_score   = ExtractDouble(content, "z_score");
   double new_p_mr      = ExtractDouble(content, "p_mr");
   double new_edge_gap  = ExtractDouble(content, "edge_gap");
   double new_band1p    = ExtractDouble(content, "band_1p");
   double new_band1n    = ExtractDouble(content, "band_1n");
   double new_band2p    = ExtractDouble(content, "band_2p");
   double new_band2n    = ExtractDouble(content, "band_2n");
   double new_band3p    = ExtractDouble(content, "band_3p");
   double new_band3n    = ExtractDouble(content, "band_3n");
   string new_zone      = ExtractString(content, "zone");
   string new_signal    = ExtractString(content, "signal_type");
   string new_trend     = ExtractString(content, "trend_bin");
   string new_trend_display  = ExtractString(content, "trend_display");
   string new_bias_display   = ExtractString(content, "bias_display");
   string new_setup_type     = ExtractString(content, "setup_type");
   string new_signal_display = ExtractString(content, "signal_display");
   string new_suppressed_by  = ExtractString(content, "suppressed_by");

   // only shift current -> previous if values actually changed
   bool changed =
      (MathAbs(new_reference - g_reference) > 0.000001) ||
      (MathAbs(new_band1p - g_band1p) > 0.000001) ||
      (MathAbs(new_band1n - g_band1n) > 0.000001) ||
      (MathAbs(new_band2p - g_band2p) > 0.000001) ||
      (MathAbs(new_band2n - g_band2n) > 0.000001) ||
      (MathAbs(new_band3p - g_band3p) > 0.000001) ||
      (MathAbs(new_band3n - g_band3n) > 0.000001);

   if(changed)
     {
      g_prev_reference = g_reference;
      g_prev_band1p = g_band1p;
      g_prev_band1n = g_band1n;
      g_prev_band2p = g_band2p;
      g_prev_band2n = g_band2n;
      g_prev_band3p = g_band3p;
      g_prev_band3n = g_band3n;

      g_reference   = new_reference;
      g_reference_shift_5 = new_reference_shift_5;
      g_sigma       = new_sigma;
      g_z_score     = new_z_score;
      g_p_mr        = new_p_mr;
      g_edge_gap    = new_edge_gap;
      g_band1p      = new_band1p;
      g_band1n      = new_band1n;
      g_band2p      = new_band2p;
      g_band2n      = new_band2n;
      g_band3p      = new_band3p;
      g_band3n      = new_band3n;
      g_zone        = new_zone;
      g_signal_type = new_signal;
      g_trend       = new_trend;
      g_trend_display  = new_trend_display;
      g_setup_type     = new_setup_type;
      g_signal_display = new_signal_display;
      g_bias_display   = new_bias_display;
      g_suppressed_by  = new_suppressed_by;
     }
   else
     {
      // still keep non-band fields fresh
      g_reference_shift_5 = new_reference_shift_5;
      g_sigma       = new_sigma;
      g_z_score     = new_z_score;
      g_p_mr        = new_p_mr;
      g_edge_gap    = new_edge_gap;
      g_zone        = new_zone;
      g_signal_type = new_signal;
      g_trend       = new_trend;
      g_trend_display  = new_trend_display;
      g_setup_type     = new_setup_type;
      g_signal_display = new_signal_display;
      g_bias_display   = new_bias_display;
      g_suppressed_by  = new_suppressed_by;
     }
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
void DrawLabel(string name, string text, int x, int y, color clr, int font_size)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);

   ObjectSetInteger(0, name, OBJPROP_CORNER, TableCorner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, font_size);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }
  

//+------------------------------------------------------------------+
string FormatBandMove(double current_value, double previous_value)
  {
   if(previous_value <= 0.0)
      return "";

   double diff = current_value - previous_value;

   if(MathAbs(diff) < 0.005)
      return " • 0.00";

   if(diff > 0.0)
      return StringFormat(" ▲ %.2f", MathAbs(diff));

   return StringFormat(" ▼ %.2f", MathAbs(diff));
  }

//+------------------------------------------------------------------+
bool IsLeapYear(int year)
{
    return ((year % 4 == 0 && year % 100 != 0) || (year % 400 == 0));
}

//+------------------------------------------------------------------+
int DaysInMonth(int year, int month)
{
    if(month == 2)
        return IsLeapYear(year) ? 29 : 28;

    if(month == 4 || month == 6 || month == 9 || month == 11)
        return 30;

    return 31;
}

//+------------------------------------------------------------------+
int DayOfWeek(int year, int month, int day)
{
    MqlDateTime dt;
    dt.year = year;
    dt.mon = month;
    dt.day = day;
    dt.hour = 0;
    dt.min = 0;
    dt.sec = 0;

    datetime t = StructToTime(dt);
    MqlDateTime out;
    TimeToStruct(t, out);

    return out.day_of_week; // Sunday = 0
}

//+------------------------------------------------------------------+
int LastSundayOfMonth(int year, int month)
{
    int last_day = DaysInMonth(year, month);
    int dow = DayOfWeek(year, month, last_day);

    return last_day - dow;
}

//+------------------------------------------------------------------+
int NthSundayOfMonth(int year, int month, int n)
{
    int dow_first = DayOfWeek(year, month, 1);
    int first_sunday = 1 + ((7 - dow_first) % 7);

    return first_sunday + 7 * (n - 1);
}

//+------------------------------------------------------------------+
bool IsDateOnOrAfter(int month, int day, int start_month, int start_day)
{
    if(month > start_month)
        return true;
    if(month == start_month && day >= start_day)
        return true;
    return false;
}

//+------------------------------------------------------------------+
bool IsDateBefore(int month, int day, int end_month, int end_day)
{
    if(month < end_month)
        return true;
    if(month == end_month && day < end_day)
        return true;
    return false;
}

//+------------------------------------------------------------------+
bool IsUKDST(datetime t)
{
    MqlDateTime dt;
    TimeToStruct(t, dt);

    int start_day = LastSundayOfMonth(dt.year, 3);
    int end_day = LastSundayOfMonth(dt.year, 10);

    bool after_start = IsDateOnOrAfter(dt.mon, dt.day, 3, start_day);
    bool before_end = IsDateBefore(dt.mon, dt.day, 10, end_day);

    return after_start && before_end;
}

//+------------------------------------------------------------------+
bool IsUSDST(datetime t)
{
    MqlDateTime dt;
    TimeToStruct(t, dt);

    int start_day = NthSundayOfMonth(dt.year, 3, 2);
    int end_day = NthSundayOfMonth(dt.year, 11, 1);

    bool after_start = IsDateOnOrAfter(dt.mon, dt.day, 3, start_day);
    bool before_end = IsDateBefore(dt.mon, dt.day, 11, end_day);

    return after_start && before_end;
}

//+------------------------------------------------------------------+
int GetBrokerUTCOffsetHours(datetime t)
{
    if(!AutoSessionDST)
        return BrokerUTCOffsetSummer;

    return IsUKDST(t) ? BrokerUTCOffsetSummer : BrokerUTCOffsetWinter;
}

//+------------------------------------------------------------------+
datetime MidnightForDate(datetime t)
{
    MqlDateTime dt;
    TimeToStruct(t, dt);

    dt.hour = 0;
    dt.min = 0;
    dt.sec = 0;

    return StructToTime(dt);
}

//+------------------------------------------------------------------+
datetime GetSessionOpenServerTime(datetime base_time, bool is_new_york)
{
    if(!AutoSessionDST)
    {
        int manual_hour = is_new_york ? ManualNewYorkOpenHour : ManualLondonOpenHour;
        int manual_minute = is_new_york ? ManualNewYorkOpenMinute : ManualLondonOpenMinute;

        return MidnightForDate(base_time) + manual_hour * 3600 + manual_minute * 60;
    }

    int broker_offset = GetBrokerUTCOffsetHours(base_time);

    int utc_minutes = 0;

    if(is_new_york)
    {
        // NYSE open = 09:30 New York time.
        // New York is UTC-5 in winter and UTC-4 in DST.
        int ny_utc_offset = IsUSDST(base_time) ? -4 : -5;
        utc_minutes = (9 * 60 + 30) - ny_utc_offset * 60;
    }
    else
    {
        // London open = 08:00 London time.
        // London is UTC+0 in winter and UTC+1 in DST.
        int london_utc_offset = IsUKDST(base_time) ? 1 : 0;
        utc_minutes = (8 * 60) - london_utc_offset * 60;
    }

    int server_minutes = utc_minutes + broker_offset * 60;

    return MidnightForDate(base_time) + server_minutes * 60;
}

//+------------------------------------------------------------------+
double GetSessionOpenPrice(bool is_new_york)
{
    datetime now_time = TimeCurrent();
    datetime session_time = GetSessionOpenServerTime(now_time, is_new_york);

    // If current broker/server time is before today's session open,
    // use the previous day's session open.
    if(now_time < session_time)
    {
        datetime previous_day = now_time - 86400;
        session_time = GetSessionOpenServerTime(previous_day, is_new_york);
    }

    int shift = iBarShift(_Symbol, _Period, session_time, false);
    if(shift < 0)
        return 0.0;

    return iOpen(_Symbol, _Period, shift);
}

//+------------------------------------------------------------------+
void DrawMoveLabel(string object_name, string label_text, double anchor_price, int x, int y)
{
    if(anchor_price <= 0.0)
    {
        DrawLabel(object_name, label_text + ": • 0.00 pts", x, y, ColorMoveFlat, TableFontSize);
        return;
    }

    double live_price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double diff = live_price - anchor_price;

    string arrow = "•";
    color clr = ColorMoveFlat;

    if(diff > 0.0)
    {
        arrow = "▲";
        clr = ColorMoveUp;
    }
    else if(diff < 0.0)
    {
        arrow = "▼";
        clr = ColorMoveDown;
    }

    DrawLabel(
        object_name,
        StringFormat("%s: %s %.2f pts", label_text, arrow, MathAbs(diff)),
        x,
        y,
        clr,
        TableFontSize
    );
}
  
//+------------------------------------------------------------------+
void DrawFromStartLabel()
  {
   ObjectDelete(0, "VWAP_FROM_START");

   int x = TableXOffset;
   int y = TableYOffset + (TableRowGap + 6) + (TableRowGap + 4) + 7 * TableRowGap + 8;

   string sigma_arrow = "•";
   color sigma_clr = ColorMoveFlat;

   if(g_reference_shift_5 > 0.0)
     {
      sigma_arrow = "▲";
      sigma_clr = ColorMoveUp;
     }
   else if(g_reference_shift_5 < 0.0)
     {
      sigma_arrow = "▼";
      sigma_clr = ColorMoveDown;
     }

   DrawLabel("VWAP_SIGMA5_SHIFT",
             StringFormat("Σ5 VWAP:   %s %.2f pts", sigma_arrow, MathAbs(g_reference_shift_5)),
             x, y, sigma_clr, TableFontSize);

   y += TableRowGap;

   double london_open_price = GetSessionOpenPrice(false);
   DrawMoveLabel("VWAP_LDN_OPEN", "LDN open", london_open_price, x, y);

   y += TableRowGap;

   double ny_open_price = GetSessionOpenPrice(true);
   DrawMoveLabel("VWAP_NY_OPEN", "NY open", ny_open_price, x, y);
  }
    

//+------------------------------------------------------------------+
void DrawCandleCountdownLabel()
{
    if(!ShowCandleCountdown)
        return;

    int period_seconds = PeriodSeconds(_Period);
    if(period_seconds <= 0)
        return;

    datetime candle_open_time = iTime(_Symbol, _Period, 0);
    datetime now_time = TimeCurrent();

    int elapsed = (int)(now_time - candle_open_time);
    int remaining = period_seconds - elapsed;

    if(remaining < 0)
        remaining = 0;
    if(remaining > period_seconds)
        remaining = period_seconds;

    int mins = remaining / 60;
    int secs = remaining % 60;

    double candle_open = iOpen(_Symbol, _Period, 0);
    double live_price = SymbolInfoDouble(_Symbol, SYMBOL_BID);

    string arrow = "•";
    if(live_price > candle_open)
        arrow = "▲";
    else if(live_price < candle_open)
        arrow = "▼";

    color countdown_clr = ColorCountdownNormal;
    if(remaining <= CountdownWarningSeconds)
        countdown_clr = ColorCountdownWarning;

    DrawLabel(
        "VWAP_CANDLE_COUNTDOWN",
        StringFormat("Candle close: %02d:%02d %s", mins, secs, arrow),
        TableXOffset,
        TableYOffset,
        countdown_clr,
        TableFontSize
    );
}
  
//+------------------------------------------------------------------+
void DrawBandTable()
  {
   int x = TableXOffset;
   int y = TableYOffset + TableRowGap + 6;

   DrawLabel("VWAP_TABLE_TITLE", "Bands", x, y, TableTextColor, TableFontSize + 1);
   y += TableRowGap + 4;

   DrawLabel("VWAP_ROW_3P",
             StringFormat("+3σ %.2f%s", g_band3p, FormatBandMove(g_band3p, g_prev_band3p)),
             x, y, ColorBand3, TableFontSize);
   y += TableRowGap;

   DrawLabel("VWAP_ROW_2P",
             StringFormat("+2σ %.2f%s", g_band2p, FormatBandMove(g_band2p, g_prev_band2p)),
             x, y, ColorBand2, TableFontSize);
   y += TableRowGap;

   DrawLabel("VWAP_ROW_1P",
             StringFormat("+1σ %.2f%s", g_band1p, FormatBandMove(g_band1p, g_prev_band1p)),
             x, y, ColorBand1, TableFontSize);
   y += TableRowGap;

   DrawLabel("VWAP_ROW_V",
             StringFormat("VW %.2f%s", g_reference, FormatBandMove(g_reference, g_prev_reference)),
             x, y, ColorVWAP, TableFontSize);
   y += TableRowGap;

   DrawLabel("VWAP_ROW_1N",
             StringFormat("-1σ %.2f%s", g_band1n, FormatBandMove(g_band1n, g_prev_band1n)),
             x, y, ColorBand1, TableFontSize);
   y += TableRowGap;

   DrawLabel("VWAP_ROW_2N",
             StringFormat("-2σ %.2f%s", g_band2n, FormatBandMove(g_band2n, g_prev_band2n)),
             x, y, ColorBand2, TableFontSize);
   y += TableRowGap;

   DrawLabel("VWAP_ROW_3N",
             StringFormat("-3σ %.2f%s", g_band3n, FormatBandMove(g_band3n, g_prev_band3n)),
             x, y, ColorBand3, TableFontSize);
  }


//+------------------------------------------------------------------+
  
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

   if(ShowBandTable && g_reference > 0)
     {
      DrawCandleCountdownLabel();
      DrawBandTable();
      DrawFromStartLabel();
     }

   if(ShowSignal || ShowZScore)
     {
      string label = StringFormat(
        "Zone: %s | Z: %.2f\nTrend: %s | Bias: %s | Setup: %s\nP(MR): %.0f%%  Edge: %.2f\nSignal: %s",
        g_zone, g_z_score,
        g_trend_display, g_bias_display, g_setup_type,
        g_p_mr * 100, g_edge_gap,
        g_signal_display
      );

      if(g_signal_display == "WAIT" && StringLen(g_suppressed_by) > 0)
        label = label + "\nReason: " + g_suppressed_by;
      Comment(label);
     }
  }
  
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
'''

    local_path = Path(output_dir) / filename
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(mql5_code.strip(), encoding="utf-8", newline="\n")
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
//| VWAP Double Overlay - Clean Context Version                      |
//| Straight execution lines from live_state.json                    |
//| Bendy context lines from live_context.json                       |
//| Only inner ±1σ context zone is faintly filled                    |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 9
#property indicator_plots   8

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
input color ColorCtxRef = clrRoyalBlue;
input color ColorCtx1   = clrLightSkyBlue;
input color ColorCtx2   = clrSilver;
input color ColorCtx3   = clrGainsboro;

// Single faint inner fill
input color ColorFill1 = clrAliceBlue;

// Buffers
double BufFill1U[];
double BufFill1L[];
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
#define MAX_CTX_POINTS 400
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
   // Fill buffers (plot 0)
   SetIndexBuffer(0, BufFill1U, INDICATOR_DATA);
   SetIndexBuffer(1, BufFill1L, INDICATOR_DATA);

   // Line buffers (plots 1..7)
   SetIndexBuffer(2, BufCtxRef, INDICATOR_DATA);
   SetIndexBuffer(3, BufCtx1P,  INDICATOR_DATA);
   SetIndexBuffer(4, BufCtx1N,  INDICATOR_DATA);
   SetIndexBuffer(5, BufCtx2P,  INDICATOR_DATA);
   SetIndexBuffer(6, BufCtx2N,  INDICATOR_DATA);
   SetIndexBuffer(7, BufCtx3P,  INDICATOR_DATA);
   SetIndexBuffer(8, BufCtx3N,  INDICATOR_DATA);

   ArraySetAsSeries(BufFill1U, true);
   ArraySetAsSeries(BufFill1L, true);
   ArraySetAsSeries(BufCtxRef, true);
   ArraySetAsSeries(BufCtx1P, true);
   ArraySetAsSeries(BufCtx1N, true);
   ArraySetAsSeries(BufCtx2P, true);
   ArraySetAsSeries(BufCtx2N, true);
   ArraySetAsSeries(BufCtx3P, true);
   ArraySetAsSeries(BufCtx3N, true);

   // Plot 0 = one fill only
   PlotIndexSetInteger(0, PLOT_DRAW_TYPE, DRAW_FILLING);
   PlotIndexSetInteger(0, PLOT_LINE_COLOR, 0, ColorFill1);
   PlotIndexSetInteger(0, PLOT_LINE_COLOR, 1, ColorFill1);
   PlotIndexSetString(0, PLOT_LABEL, "Ctx Inner Fill");

   // Plot 1 = context reference
   PlotIndexSetInteger(1, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(1, PLOT_LINE_COLOR, 0, ColorCtxRef);
   PlotIndexSetInteger(1, PLOT_LINE_WIDTH, 2);
   PlotIndexSetString(1, PLOT_LABEL, "Ctx Ref");

   // Plot 2 = +1
   PlotIndexSetInteger(2, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(2, PLOT_LINE_COLOR, 0, ColorCtx1);
   PlotIndexSetInteger(2, PLOT_LINE_STYLE, STYLE_DOT);
   PlotIndexSetInteger(2, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(2, PLOT_LABEL, "Ctx 1+");

   // Plot 3 = -1
   PlotIndexSetInteger(3, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(3, PLOT_LINE_COLOR, 0, ColorCtx1);
   PlotIndexSetInteger(3, PLOT_LINE_STYLE, STYLE_DOT);
   PlotIndexSetInteger(3, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(3, PLOT_LABEL, "Ctx 1-");

   // Plot 4 = +2
   PlotIndexSetInteger(4, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(4, PLOT_LINE_COLOR, 0, ColorCtx2);
   PlotIndexSetInteger(4, PLOT_LINE_STYLE, STYLE_DASH);
   PlotIndexSetInteger(4, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(4, PLOT_LABEL, "Ctx 2+");

   // Plot 5 = -2
   PlotIndexSetInteger(5, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(5, PLOT_LINE_COLOR, 0, ColorCtx2);
   PlotIndexSetInteger(5, PLOT_LINE_STYLE, STYLE_DASH);
   PlotIndexSetInteger(5, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(5, PLOT_LABEL, "Ctx 2-");

   // Plot 6 = +3
   PlotIndexSetInteger(6, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(6, PLOT_LINE_COLOR, 0, ColorCtx3);
   PlotIndexSetInteger(6, PLOT_LINE_STYLE, STYLE_DASHDOT);
   PlotIndexSetInteger(6, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(6, PLOT_LABEL, "Ctx 3+");

   // Plot 7 = -3
   PlotIndexSetInteger(7, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(7, PLOT_LINE_COLOR, 0, ColorCtx3);
   PlotIndexSetInteger(7, PLOT_LINE_STYLE, STYLE_DASHDOT);
   PlotIndexSetInteger(7, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(7, PLOT_LABEL, "Ctx 3-");

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

   // newest closed exported point goes to shift 1
   for(int i = 0; i < g_ctx_count; i++)
     {
      int shift = g_ctx_count - i;
      if(shift >= rates_total) continue;

      BufFill1U[shift] = g_ctx_1p[i];
      BufFill1L[shift] = g_ctx_1n[i];

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