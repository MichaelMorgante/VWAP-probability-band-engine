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
input bool AnchorBandsToStartup = true;
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
input color ColorSessionLabel = clrMediumPurple;

// Candle countdown
input bool ShowCandleCountdown = true;
input color ColorCountdownNormal = clrWhite;

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
string g_adaptive_trend_direction = "NONE";
string g_adaptive_trend_state = "NO_TREND";
string g_adaptive_shift_class = "WEAK_SHIFT";
string g_adaptive_spread_state = "NOT_EXPANDING";
string g_adaptive_orange_pressure = "NO_ORANGE_PRESSURE";
string g_adaptive_compression = "NONE";
string g_adaptive_trend_health = "NO_TREND";

double g_adaptive_lane_count = 0.0;
double g_adaptive_red_shift = 0.0;
double g_adaptive_current_red_shift = 0.0;
double g_adaptive_shift_ratio = 0.0;
string g_startup_mode = "";
string g_startup_label = "";
string g_startup_overlay_visual_start = "";
string g_startup_start_uk = "";
string g_startup_start_server = "";
string g_startup_line_start_uk = "";
string g_startup_line_start_server = "";
string g_startup_anchor_active = "NO";
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
   EventSetTimer(1); // poll JSON every 1 seconds
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
   string new_adaptive_trend_direction = ExtractString(content, "adaptive_trend_direction");
   string new_adaptive_trend_state = ExtractString(content, "adaptive_trend_state");
   string new_adaptive_shift_class = ExtractString(content, "adaptive_shift_class");
   string new_adaptive_spread_state = ExtractString(content, "adaptive_spread_state");
   string new_adaptive_orange_pressure = ExtractString(content, "adaptive_orange_pressure");
   string new_adaptive_compression = ExtractString(content, "adaptive_compression");
   string new_adaptive_trend_health = ExtractString(content, "adaptive_trend_health");

   double new_adaptive_lane_count = ExtractDouble(content, "adaptive_lane_count");
   double new_adaptive_red_shift = ExtractDouble(content, "adaptive_red_shift");
   double new_adaptive_current_red_shift = ExtractDouble(content, "adaptive_current_red_shift");
   double new_adaptive_shift_ratio = ExtractDouble(content, "adaptive_shift_ratio");
   string new_startup_mode = ExtractString(content, "startup_mode");
   string new_startup_label = ExtractString(content, "startup_label");
   string new_startup_overlay_visual_start = ExtractString(content, "startup_overlay_visual_start");
   string new_startup_start_uk = ExtractString(content, "startup_start_uk");
   string new_startup_start_server = ExtractString(content, "startup_start_server");
   string new_startup_line_start_uk = ExtractString(content, "startup_line_start_uk");
   string new_startup_line_start_server = ExtractString(content, "startup_line_start_server");
   string new_startup_anchor_active = ExtractString(content, "startup_anchor_active");

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

      g_adaptive_trend_direction = new_adaptive_trend_direction;
      g_adaptive_trend_state = new_adaptive_trend_state;
      g_adaptive_shift_class = new_adaptive_shift_class;
      g_adaptive_spread_state = new_adaptive_spread_state;
      g_adaptive_orange_pressure = new_adaptive_orange_pressure;
      g_adaptive_compression = new_adaptive_compression;
      g_adaptive_trend_health = new_adaptive_trend_health;

      g_adaptive_lane_count = new_adaptive_lane_count;
      g_adaptive_red_shift = new_adaptive_red_shift;
      g_adaptive_current_red_shift = new_adaptive_current_red_shift;
      g_adaptive_shift_ratio = new_adaptive_shift_ratio;
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

      g_adaptive_trend_direction = new_adaptive_trend_direction;
      g_adaptive_trend_state = new_adaptive_trend_state;
      g_adaptive_shift_class = new_adaptive_shift_class;
      g_adaptive_spread_state = new_adaptive_spread_state;
      g_adaptive_orange_pressure = new_adaptive_orange_pressure;
      g_adaptive_compression = new_adaptive_compression;
      g_adaptive_trend_health = new_adaptive_trend_health;

      g_adaptive_lane_count = new_adaptive_lane_count;
      g_adaptive_red_shift = new_adaptive_red_shift;
      g_adaptive_current_red_shift = new_adaptive_current_red_shift;
      g_adaptive_shift_ratio = new_adaptive_shift_ratio;
     }

     g_startup_mode = new_startup_mode;
     g_startup_label = new_startup_label;
     g_startup_overlay_visual_start = new_startup_overlay_visual_start;
     g_startup_start_uk = new_startup_start_uk;
     g_startup_start_server = new_startup_start_server;
     g_startup_line_start_uk = new_startup_line_start_uk;
     g_startup_line_start_server = new_startup_line_start_server;
     g_startup_anchor_active = new_startup_anchor_active;
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
    if(ObjectFind(0, name) >= 0 && ObjectGetInteger(0, name, OBJPROP_TYPE) != OBJ_HLINE)
        ObjectDelete(0, name);

    if(ObjectFind(0, name) < 0)
        ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);

    ObjectSetDouble(0, name, OBJPROP_PRICE, price);
    ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
    ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
    ObjectSetInteger(0, name, OBJPROP_STYLE, style);
    ObjectSetInteger(0, name, OBJPROP_BACK, true);
  }

//+------------------------------------------------------------------+
datetime GetStartupAnchorTime()
{
    if(!AnchorBandsToStartup)
        return 0;

    if(g_startup_anchor_active != "YES")
        return 0;

    string anchor_text = g_startup_line_start_server;

    // Backward compatibility: if the new line-start field is missing,
    // fall back to the original selected session start.
    if(StringLen(anchor_text) < 10)
        anchor_text = g_startup_start_server;

    if(StringLen(anchor_text) < 10)
        return 0;

    datetime anchor_time = StringToTime(anchor_text);

    if(anchor_time <= 0)
        return 0;

    if(anchor_time >= TimeCurrent())
        return 0;

    return anchor_time;
}

//+------------------------------------------------------------------+
void DrawBandLine(string name, double price, color clr, int width, int style)
{
    datetime anchor_time = GetStartupAnchorTime();

    if(anchor_time <= 0)
    {
        DrawHLine(name, price, clr, width, style);
        return;
    }

    datetime end_time = TimeCurrent();

    if(ObjectFind(0, name) >= 0 && ObjectGetInteger(0, name, OBJPROP_TYPE) != OBJ_TREND)
        ObjectDelete(0, name);

    if(ObjectFind(0, name) < 0)
        ObjectCreate(0, name, OBJ_TREND, 0, anchor_time, price, end_time, price);

    ObjectMove(0, name, 0, anchor_time, price);
    ObjectMove(0, name, 1, end_time, price);

    ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
    ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
    ObjectSetInteger(0, name, OBJPROP_STYLE, style);
    ObjectSetInteger(0, name, OBJPROP_BACK, true);
    ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, true);
    ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
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
    int period_seconds = PeriodSeconds(_Period);
    if(period_seconds <= 0)
        period_seconds = 60;

    // Search backwards up to 10 days to find a real tradable session bar.
    for(int d = 0; d < 10; d++)
    {
        datetime base_time = now_time - d * 86400;
        datetime session_time = GetSessionOpenServerTime(base_time, is_new_york);

        // Do not use a future session time.
        if(session_time > now_time)
            continue;

        int shift = iBarShift(_Symbol, _Period, session_time, false);
        if(shift < 0)
            continue;

        datetime bar_time = iTime(_Symbol, _Period, shift);

        // Reject stale bars from weekends/closed markets.
        // This stops Sunday/Monday pre-open from accidentally using Friday's bar.
        int max_gap = MathMax(3 * period_seconds, 180);
        if(MathAbs((int)(bar_time - session_time)) > max_gap)
            continue;

        double open_price = iOpen(_Symbol, _Period, shift);
        if(open_price > 0.0)
            return open_price;
    }

    return 0.0;
}

//+------------------------------------------------------------------+
void DrawMoveLabel(string object_name, string label_text, double anchor_price, int x, int y)
  {
   if(anchor_price <= 0.0)
     {
      DrawLabel(object_name, label_text + ": • 0.00 pts", x, y, ColorSessionLabel, TableFontSize);
      return;
     }

   double live_price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double diff = live_price - anchor_price;

   string arrow = "•";

   if(diff > 0.0)
      arrow = "▲";
   else if(diff < 0.0)
      arrow = "▼";

   DrawLabel(
      object_name,
      StringFormat("%s: %s %.2f pts", label_text, arrow, MathAbs(diff)),
      x,
      y,
      ColorSessionLabel,
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
   color countdown_clr = ColorCountdownNormal;

   if(live_price > candle_open)
     {
      arrow = "▲";
      countdown_clr = ColorMoveUp;
     }
   else if(live_price < candle_open)
     {
      arrow = "▼";
      countdown_clr = ColorMoveDown;
     }

   DrawLabel("VWAP_CANDLE_COUNTDOWN",
             StringFormat("Candle close: %02d:%02d %s", mins, secs, arrow),
             TableXOffset,
             TableYOffset,
             countdown_clr,
             TableFontSize);
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
   if(ShowBands && g_reference > 0) {
       DrawBandLine("VWAP_REF", g_reference, ColorVWAP, 2, STYLE_SOLID);
       DrawBandLine("VWAP_1P", g_band1p, ColorBand1, 1, STYLE_DOT);
       DrawBandLine("VWAP_1N", g_band1n, ColorBand1, 1, STYLE_DOT);
       DrawBandLine("VWAP_2P", g_band2p, ColorBand2, 1, STYLE_DASH);
       DrawBandLine("VWAP_2N", g_band2n, ColorBand2, 1, STYLE_DASH);
       DrawBandLine("VWAP_3P", g_band3p, ColorBand3, 1, STYLE_DASHDOT);
       DrawBandLine("VWAP_3N", g_band3n, ColorBand3, 1, STYLE_DASHDOT);
  }

   DrawCandleCountdownLabel();

   if(ShowBandTable && g_reference > 0)
     {
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

      label = label + "\n\nAdaptive Trend Health";

      label = label + StringFormat(
          "\nState: %s | Count: %.0f",
          g_adaptive_trend_state,
          g_adaptive_lane_count
      );

      label = label + StringFormat(
          "\nRed shift: %.2f | Current: %.2f | Ratio: %.0f%%",
          g_adaptive_red_shift,
          g_adaptive_current_red_shift,
          g_adaptive_shift_ratio * 100.0
      );

      label = label + StringFormat(
          "\nShift: %s",
          g_adaptive_shift_class
      );

      label = label + StringFormat(
          "\nSpread: %s",
          g_adaptive_spread_state
      );

      label = label + StringFormat(
          "\nOrange: %s",
          g_adaptive_orange_pressure
      );

      label = label + StringFormat(
          "\nCompression: %s",
          g_adaptive_compression
      );

      label = label + StringFormat(
          "\nHealth: %s",
          g_adaptive_trend_health
      );


      Comment(label);
     }
  }

//+------------------------------------------------------------------+

//+------------------------------------------------------------------+