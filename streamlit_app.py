import os
import re
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO, StringIO
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
from weasyprint import HTML

# -------------------------------------------------------------------------
# GLOBAL CONFIGURATION & STYLING
# -------------------------------------------------------------------------
st.set_page_config(
    page_title="VVF Forms Automation",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stAppHeader, .css-18ni0ed {
        background-color: #34a379 !important;
    }
    div[data-testid="stToolbar"] {
        visibility: hidden;
        height: 0;
        margin: 0;
        padding: 0;
    }
    .stButton>button {
        border-radius: 4px;
        font-weight: bold;
    }
    </style>
""",
    unsafe_allow_html=True,
)

DEFAULT_SPREADSHEET_ID = "1fGpggupf2IoTaKX7Vd2i3uyHUc_MI2aI7GCulbw-s6Q"
LOCAL_SERVICE_ACCOUNT = Path(__file__).with_name("neon-webbing-314108-164f194cf012.json")
DEFAULT_START_SERIAL = 0

ATT_SHEET = "Max_Min_Serial"
CONSENT_SHEET = "Consent_series"

# -------------------------------------------------------------------------
# HELPERS & GOOGLE SHEETS AUTHENTICATION
# -------------------------------------------------------------------------
def get_secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

def has_secret(name):
    try:
        return name in st.secrets
    except Exception:
        return False

def get_worksheet(worksheet_name=None):
    spreadsheet_id = get_secret("spreadsheet_id", DEFAULT_SPREADSHEET_ID)
    has_secret_account = has_secret("gcp_service_account")
    has_local_account = LOCAL_SERVICE_ACCOUNT.exists()

    if not spreadsheet_id or not (has_secret_account or has_local_account):
        return None

    if has_secret_account:
        client = gspread.service_account_from_dict(get_secret("gcp_service_account"))
    else:
        client = gspread.service_account(filename=str(LOCAL_SERVICE_ACCOUNT))

    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet_name = worksheet_name or "Form Responses 1"

    try:
        return spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        return None

def get_sheet_df(worksheet_name):
    worksheet = get_worksheet(worksheet_name)
    if worksheet is None:
        return pd.DataFrame()
    values = worksheet.get_all_values()
    if len(values) < 2:
        return pd.DataFrame()
    headers = [h.strip() for h in values[0]]
    df = pd.DataFrame(values[1:], columns=headers)
    return df

def find_count_column(columns, form_type):
    patterns = {
        "Individual Consent": r"individual|consent",
        "Group Consent": r"group",
        "Attendance": r"training attendance|attendance",
    }
    pattern = patterns.get(form_type, r"attendance")

    for col in columns:
        if re.search(pattern, col, re.IGNORECASE):
            return col

    for col in columns:
        if re.search(r"number|forms|count", col, re.IGNORECASE):
            return col
    return None

def build_serial_preview(selected_df, form_type, target_sheet_name):
    if selected_df.empty:
        return pd.DataFrame()

    fo_col = next((c for c in selected_df.columns if c.strip().lower() == "field officer"), None)
    if not fo_col:
        raise ValueError("Column 'Field Officer' missing in source sheet.")

    count_col = find_count_column(selected_df.columns, form_type)
    if not count_col:
        raise ValueError(f"Could not locate form count column for '{form_type}'.")

    dest_df = get_sheet_df(target_sheet_name)
    if not dest_df.empty and "Max" in dest_df.columns:
        numeric_max = pd.to_numeric(dest_df["Max"], errors="coerce")
        current_max = int(numeric_max.max()) if not numeric_max.dropna().empty else DEFAULT_START_SERIAL
    else:
        current_max = DEFAULT_START_SERIAL

    records = []
    for _, row in selected_df.iterrows():
        raw_val = str(row.get(count_col, "0"))
        digits = re.sub(r"[^\d]", "", raw_val)
        count = int(digits) if digits else 0

        if count <= 0:
            continue

        min_val = current_max + 1
        max_val = current_max + count

        item = {
            "Facilitator": row[fo_col],
            "Min": min_val,
            "Max": max_val,
        }
        if form_type in ["Individual Consent", "Group Consent"]:
            item["NO_of_Sheets"] = count

        records.append(item)
        current_max = max_val

    return pd.DataFrame(records)

# -------------------------------------------------------------------------
# HTML & WEASYPRINT PDF GENERATOR ENGINE
# -------------------------------------------------------------------------
def render_individual_consent_page(serial_no, facilitator):
    formatted_sn = f"{serial_no:05d}"
    
    def form_html(copy_name):
        return f"""
        <div class="consent-box">
            <div class="header">
                <img src="VV-logo.png" class="logo" alt="Logo" onerror="this.style.display='none'">
                <div class="header-center">
                    <div class="title">PHOTO / VIDEO CONSENT FORM</div>
                </div>
                <div class="serial-box">SN: {formatted_sn}</div>
            </div>
            <p class="consent-text">
                I, <span class="underline long"></span> grant permission to Vibrant Village Foundation for the use of the video(s), photograph(s) and electronic media images as identified below in any presentation of any and all kind whatsoever.
            </p>
            <p class="consent-text">
                I understand that I may revoke this authorization at any time by notifying Vibrant Village Foundation-Kenya in writing. The revocation will not affect any actions taken before receipt of this written notification.
            </p>
            <p class="consent-text">
                Images will be stored in a secure location and only authorized staff will have access to them. They will be kept as long as they are relevant and after that time destroyed or archived.
            </p>
            <table class="form-table">
                <tr>
                    <td class="label">County</td><td class="fill"></td>
                    <td class="label">Sub County</td><td class="fill"></td>
                </tr>
                <tr>
                    <td class="label">Phone</td><td class="fill"></td>
                    <td class="label">Location</td><td class="fill"></td>
                </tr>
                <tr>
                    <td class="label">Image(s) Description</td><td class="fill" colspan="3"></td>
                </tr>
                <tr>
                    <td class="label">Signature</td><td class="fill"></td>
                    <td class="label">Date</td><td class="fill"></td>
                </tr>
            </table>
            <div class="officer-note">Officer Incharge: {facilitator}</div>
            <div class="copy-note">({copy_name})</div>
        </div>
        """

    return f"""
    <div style="page-break-after:always; height: 100vh; display: flex; flex-direction: column; justify-content: space-between;">
        {form_html("Participant Copy")}
        <div class="cut-line"><span>✂ CUT HERE ✂</span></div>
        {form_html("Office Copy")}
    </div>
    """

def render_group_consent_page(serial_no, facilitator):
    formatted_sn = f"{serial_no:05d}"
    rows_1_15 = "".join(f"<tr><td style='text-align:center;'>{i}</td><td></td><td></td><td></td></tr>" for i in range(1, 16))
    rows_16_30 = "".join(f"<tr><td style='text-align:center;'>{i}</td><td></td><td></td><td></td></tr>" for i in range(16, 31))

    return f"""
    <div style="page-break-after:always;" class="group-consent-box">
        <div class="group-header">
            <img src="VV-logo.png" class="group-logo" alt="Logo" onerror="this.style.display='none'">
            <div class="group-title">GROUP PHOTO/VIDEO CONSENT FORM</div>
            <div class="group-sn">SN: {formatted_sn}</div>
        </div>
        <p class="group-consent-text">
            I grant permission to Vibrant Village Foundation for the use of the Video(s), photograph(s) and electronic media images as identified below in any presentation of any and all kind whatsoever. I understand that I may revoke this authorization at any time by notifying Vibrant Village Foundation-Kenya in writing. The revocation will not affect any actions taken before the receipt of this written notification. Images will be stored in a secure location and only authorized staff will have access to them. They will be kept as long as they are relevant and after that time destroyed or archived.
        </p>
        <div class="group-meta-row">
            <div class="meta-item"><span>Activity: </span><span class="meta-underline"></span></div>
            <div class="meta-item"><span>Place: </span><span class="meta-underline"></span></div>
            <div class="meta-item"><span>Date: </span><span class="meta-underline"></span></div>
        </div>
        <div class="tables-flex">
            <table class="group-side-table">
                <tr><th style="width: 32px;">No</th><th>Name</th><th style="width: 150px;">Phone</th><th style="width: 140px;">Signature</th></tr>
                {rows_1_15}
            </table>
            <table class="group-side-table">
                <tr><th style="width: 32px;">No</th><th>Name</th><th style="width: 150px;">Phone</th><th style="width: 140px;">Signature</th></tr>
                {rows_16_30}
            </table>
        </div>
        <div class="group-footer">Officer Incharge: {facilitator}</div>
    </div>
    """

def render_attendance_page(serial_no, facilitator):
    rows_35 = "".join(
        f"<tr><td class='nocol'>{i}</td><td class='namecol'></td><td class='vvidcol'></td><td class='gendercol'></td><td class='agecol'></td><td class='phonecol'></td><td class='signcol'></td></tr>"
        for i in range(1, 36)
    )
    
    participants = ["Parents", "Teachers", "Partners", "Farmers", "Pupils", "Groups", "Lead Farmers"]
    participants_html = "".join(
        f"<div class='participant-item'><div class='participant-label'>{p}</div><span class='small-box'></span></div>"
        for p in participants
    )

    return f"""
    <div style="page-break-after:always;">
        <div class="row">
            <div style="width:20%;"><img src="VV-logo.png" style="width:80px;" alt="Logo" onerror="this.style.display='none'"></div>
            <div class="title" style="width:38%; text-align:left;">VVF ATTENDANCE SHEET</div>
            <div style="width:42%; text-align:right;"><b>Serial No: {serial_no} ({facilitator})</b></div>
        </div>
        <div class="section" style="width:100%; text-align:center;">School/Group Name: <span class="underline wide"></span></div>
        <div class="top-flex">
            <div class="left-block">
                <div class="programs-vertical">
                    <div class="program-item">PEEL <span class="small-box"></span></div>
                    <div class="program-item">PRAT <span class="small-box"></span></div>
                    <div class="program-item">REID <span class="small-box"></span></div>
                </div>
                <div class="participants-row">
                    {participants_html}
                </div>
            </div>
            <div class="right-block" style="text-align:right;">
                <div><span class="field-label">COUNTY:</span><span class="underline"></span></div>
                <div><span class="field-label">SUB-COUNTY:</span><span class="underline"></span></div>
                <div><span class="field-label">WARD:</span><span class="underline"></span></div>
            </div>
        </div>
        <div class="row sect" style="margin-top:4px; gap:20px;">
            <div style="width:50%;">
                <div><span class="field-label">TOPIC: </span><span class="underline" style="width:300px;"></span></div><br>
                <div><span class="field-label"> </span><span class="underline" style="width:300px;"></span></div>
            </div>
            <div style="width:50%;">
                <div><span class="field-label">TOPIC DETAILS: </span><span class="underline" style="width:300px;"></span></div><br>
                <div><span class="field-label"> </span><span class="underline" style="width:300px;"></span></div>
            </div>
        </div>
        <table>
            <tr>
                <th rowspan="2" class="nocol" style="width:25px;">No</th>
                <th rowspan="2" class="namecol name-header" style="width:220px;">Name</th>
                <th colspan="4" class="particulars-header">PARTICULARS</th>
                <th rowspan="2" class="signcol sign-header" style="width:120px;">Sign / Grade</th>
            </tr>
            <tr>
                <th class="vvidcol vvid-header" style="width:90px;">VVID</th>
                <th class="gendercol gender-header" style="width:30px;">Gender<br>(M/F)</th>
                <th class="agecol age-header" style="width:110px;">Less than 35 Yrs<br>(Yes/No)/YOB</th>
                <th class="phonecol phone-header" style="width:180px;">Phone</th>
            </tr>
            {rows_35}
        </table>
        <div class="section" style="margin-top:10px;"><b>FACILITATORS: </b><span class="underline" style="width:180px;"></span> / <span class="underline" style="width:180px;"></span> / <span class="underline" style="width:180px;"></span></div>
        <div class="section" style="margin-top:10px;"><b>SIGN: </b><span class="underline" style="width:160px;"></span> / <span class="underline" style="width:160px;"></span> / <span class="underline" style="width:160px;"></span> / Date: <span class="underline" style="width:100px;"></span></div>
    </div>
    """

def create_pdf_document(preview_df, form_type):
    pages_html = ""
    for _, row in preview_df.iterrows():
        facilitator = row["Facilitator"]
        for sn in range(int(row["Min"]), int(row["Max"]) + 1):
            if form_type in ["Individual Consent", "Consent"]:
                pages_html += render_individual_consent_page(sn, facilitator)
            elif form_type == "Group Consent":
                pages_html += render_group_consent_page(sn, facilitator)
            else:
                pages_html += render_attendance_page(sn, facilitator)

    if form_type in ["Individual Consent", "Consent"]:
        css_style = """
        @page { size: A4; margin: 0.3cm 0.4cm; }
        body { font-family: 'Times New Roman', serif; font-size: 11.5pt; color: #000; line-height: 1.35; margin: 0; }
        .consent-box { border: 1.2px solid #000; padding: 14px 18px; flex: 1; display: flex; flex-direction: column; justify-content: space-between; box-sizing: border-box; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .logo { width: 80px; height: auto; }
        .header-center { text-align: center; flex: 1; }
        .title { font-size: 18px; font-weight: bold; text-transform: uppercase; }
        .serial-box { font-size: 16px; font-weight: bold; min-width: 100px; text-align: right; }
        .consent-text { margin: 0 0 6px 0; text-align: justify; }
        .underline { display: inline-block; border-bottom: 1px solid #000; vertical-align: bottom; height: 16px; }
        .underline.long { width: 260px; }
        .form-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
        .form-table td { border: 1px solid #000; padding: 8px 10px; height: 32px; vertical-align: middle; }
        .label { width: 18%; font-weight: bold; background: #fafafa; }
        .fill { width: 32%; }
        .officer-note { margin-top: 6px; font-size: 11pt; font-weight: normal; text-align: left; }
        .copy-note { text-align: center; font-style: italic; font-size: 11px; margin-top: 2px; }
        .cut-line { margin: 8px 0; text-align: center; position: relative; }
        .cut-line:before { content: ''; position: absolute; top: 50%; left: 0; right: 0; border-top: 2px dashed #000; z-index: 0; }
        .cut-line span { position: relative; background: #fff; padding: 0 12px; font-weight: bold; font-size: 11px; z-index: 1; }
        """
    elif form_type == "Group Consent":
        css_style = """
        @page { size: A4 landscape; margin: 0.35cm 0.5cm; }
        body { font-family: 'Times New Roman', serif; font-size: 11pt; color: #000; line-height: 1.3; margin: 0; }
        .group-consent-box { width: 100%; box-sizing: border-box; }
        .group-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .group-logo { width: 115px; height: auto; }
        .group-title { font-size: 21px; font-weight: bold; text-align: center; flex: 1; text-transform: uppercase; }
        .group-sn { font-size: 18px; font-weight: bold; min-width: 120px; text-align: right; }
        .group-consent-text { text-align: justify; font-size: 11.5pt; margin: 0 0 10px 0; line-height: 1.35; }
        .group-meta-row { display: flex; justify-content: space-between; align-items: center; font-size: 12pt; font-weight: bold; margin-bottom: 10px; }
        .meta-item { display: flex; align-items: flex-end; flex: 1; }
        .meta-underline { border-bottom: 1px solid #000; flex: 1; margin-right: 20px; height: 16px; display: inline-block; }
        .tables-flex { display: flex; justify-content: space-between; gap: 14px; margin-top: 6px; }
        .group-side-table { width: 49.5%; border-collapse: collapse; }
        .group-side-table th, .group-side-table td { border: 1px solid #000; padding: 5px 6px; font-size: 11pt; height: 28px; box-sizing: border-box; }
        .group-side-table th { background: #ffffff; font-weight: bold; text-align: left; }
        .group-footer { margin-top: 12px; font-size: 11.5pt; font-weight: normal; text-align: left; }
        """
    else:
        css_style = """
        @page { size: A4; margin: 0.50cm 0.65cm; }
        body { font-family: 'Times New Roman', serif; margin: 0; font-size: 12px; }
        .row { display: flex; justify-content: space-between; align-items: flex-start; }
        .title { text-align: center; font-size: 22px; font-weight: bold; }
        .section { margin-top: 5px; font-weight: bold; font-size: 16px; }
        .sect { margin-top: 5px; font-weight: bold; font-size: 12px; }
        .small-box { width: 14px; height: 14px; border: 1px solid #000; display: inline-block; margin-left: 2px; vertical-align: middle; box-sizing: border-box; }
        .underline { border-bottom: 1px solid #000; display: inline-block; width: 150px; }
        .wide { width: 320px; }
        th, td { border: 1px solid #000; padding: 2px; font-size: 10px; height: 15px; text-align: center; vertical-align: middle; }
        th { background: #faf7f7; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; margin-top: 4px; }
        .nocol { width: 25px !important; }
        .namecol { width: 230px !important; }
        .vvidcol { width: 90px !important; }
        .gendercol { width: 30px !important; }
        .agecol { width: 110px !important; }
        .phonecol { width: 180px !important; }
        .signcol { width: 120px !important; }
        .name-header, .particulars-header { font-size: 14px; }
        .sign-header { font-size: 13px; }
        .vvid-header, .phone-header { font-size: 12px; }
        .gender-header { font-size: 11px; line-height: 1.1; }
        .age-header { font-size: 10px; line-height: 1.1; }
        .top-flex { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-top: 5px; }
        .left-block { display: flex; gap: 12px; width: 58%; }
        .programs-vertical { display: flex; flex-direction: column; gap: 3px; min-width: 70px; }
        .program-item { display: flex; align-items: center; gap: 4px; font-size: 12px; }
        .participants-row { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 1px; justify-content: flex-start; }
        .participant-item { margin: 0; padding: 2px 4px; text-align: center; line-height: 1; min-width: 56px; }
        .participant-label { font-size: 12px; margin-bottom: 4px; }
        .right-block { width: 40%; font-size: 12px; font-weight: bold; line-height: 1.8; }
        .field-label { display: inline-block; min-width: 95px; }
        """

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head><style>{css_style}</style></head>
    <body>{pages_html}</body>
    </html>
    """

    pdf_io = BytesIO()
    HTML(string=full_html, base_url=str(Path(__file__).parent)).write_pdf(pdf_io)
    pdf_io.seek(0)
    return pdf_io.getvalue()

# -------------------------------------------------------------------------
# EMAIL DISPATCH HELPER
# -------------------------------------------------------------------------
def send_dispatch_email(pdf_bytes, filename, form_type, preview_df, master_df):
    smtp_user = get_secret("smtp_user")
    smtp_pass = get_secret("smtp_password")
    smtp_from = get_secret("smtp_from")
    smtp_recipients_raw = get_secret("smtp_recipients")

    if isinstance(smtp_recipients_raw, str):
        recipients = [part.strip() for part in re.split(r"[,;]", smtp_recipients_raw) if part.strip()]
    elif isinstance(smtp_recipients_raw, (list, tuple, set)):
        recipients = [str(item).strip() for item in smtp_recipients_raw if str(item).strip()]
    else:
        recipients = []

    if not smtp_user or not smtp_pass:
        st.error("SMTP credentials (`smtp_user` & `smtp_password`) missing from secrets.")
        return

    if not smtp_from:
        st.error("SMTP sender address (`smtp_from`) missing from secrets.")
        return

    if not recipients:
        st.error("SMTP recipients missing from secrets (`smtp_recipients`).")
        return

    min_s = int(preview_df["Min"].min())
    max_s = int(preview_df["Max"].max())
    min_str = f"{min_s:05d}" if form_type in ["Individual Consent", "Group Consent"] else str(min_s)
    max_str = f"{max_s:05d}" if form_type in ["Individual Consent", "Group Consent"] else str(max_s)

    fo_names = [f.strip() for f in preview_df["Facilitator"].unique()]
    
    fo_col = next((c for c in master_df.columns if c.strip().lower() == "field officer"), None)
    email_col = next((c for c in master_df.columns if "email" in c.lower()), None)
    
    fo_emails = []
    if fo_col and email_col:
        matched = master_df[master_df[fo_col].str.strip().isin(fo_names)]
        fo_emails = list(matched[email_col].dropna().unique())

    fo_list_str = ", ".join(fo_names)

    msg = MIMEMultipart()
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)
    if fo_emails:
        msg["Cc"] = ", ".join(fo_emails)
    msg["Subject"] = f"VVF {form_type} PDF {min_str} - {max_str}"

    body_text = f"""Hello,

Please find the attached {form_type} sheets covering serial numbers {min_str} to {max_str} for printing.

Target Field Officers: {fo_list_str}

Regards,
MEAL Automated Systems Portal
"""
    msg.attach(MIMEText(body_text, "plain"))

    part = MIMEApplication(pdf_bytes, Name=filename)
    part["Content-Disposition"] = f'attachment; filename="{filename}"'
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_user, smtp_pass)
        all_to = recipients + fo_emails
        server.sendmail(smtp_from, all_to, msg.as_string())

# -------------------------------------------------------------------------
# APPLICATION USER INTERFACE & STATE
# -------------------------------------------------------------------------
st.title("VVF Forms Automation")

with st.sidebar:
    st.header("Control Panel")

    st.subheader("1. Form Type Selector")
    form_type = st.radio(
        "Select Document Type:",
        ["Attendance", "Individual Consent", "Group Consent"],
        index=1,
    )

    st.divider()
    st.subheader("2. Data Actions")
    btn_stage = st.button("Stage & Calculate Serials", type="primary", use_container_width=True)
    btn_append = st.button("Append Serials to Sheet", use_container_width=True)

    st.divider()
    st.subheader("3. Native Printing Pipeline")
    btn_gen_pdf = st.button("1. Generate PDF Document", type="primary", use_container_width=True)
    btn_email = st.button("2. Send Email", use_container_width=True)

# Fetch Source Data
if "master_df" not in st.session_state:
    with st.spinner("Fetching master sheet responses..."):
        df = get_sheet_df("Form Responses 1")
        st.session_state.master_df = df.tail(5) if not df.empty else pd.DataFrame()

master_df = st.session_state.get("master_df", pd.DataFrame())

st.subheader("Step 1: Master Form Responses (Latest Entries First)")
selected_rows = pd.DataFrame()

if not master_df.empty:
    dt_event = st.dataframe(
        master_df,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="multi-row",
        key="master_table",
    )
    sel_idx = dt_event.selection.rows
    if sel_idx:
        selected_rows = master_df.iloc[sel_idx]
    st.caption(f"📌 {len(selected_rows)} row(s) selected from table.")
else:
    st.warning("No data found in source sheet 'Form Responses 1'.")

target_sheet = CONSENT_SHEET if form_type in ["Individual Consent", "Group Consent"] else ATT_SHEET

# Stage Calculation
if btn_stage:
    if selected_rows.empty:
        st.error("Please select at least one row from the master requests table.")
    else:
        try:
            preview_df = build_serial_preview(selected_rows, form_type, target_sheet)
            st.session_state.preview_df = preview_df
            if not preview_df.empty:
                st.success("Serials staged and calculated successfully.")
            else:
                st.warning("Selected rows contain 0 or empty form counts.")
        except Exception as e:
            st.error(f"Calculation Fault: {e}")

preview_df = st.session_state.get("preview_df", pd.DataFrame())

st.divider()
st.subheader("Step 2: Calculated Serial Previews")
if not preview_df.empty:
    st.dataframe(preview_df, hide_index=True, use_container_width=True)
else:
    st.info("No calculations staged yet. Select entries and click **Stage & Calculate Serials**.")

# Append Logic
if btn_append:
    if preview_df.empty:
        st.error("No preview available to append. Please stage serial calculations first.")
    else:
        try:
            ws = get_worksheet(target_sheet)
            if ws:
                ws.append_rows(preview_df.astype(str).values.tolist())
                st.success(f"Serials successfully logged into {target_sheet}!")
            else:
                st.error(f"Worksheet '{target_sheet}' not found.")
        except Exception as e:
            st.error(f"Append failed: {e}")

# Generate PDF Logic
if btn_gen_pdf:
    if preview_df.empty:
        st.error("Please stage calculations before compiling the PDF.")
    else:
        try:
            with st.spinner(f"Compiling {form_type} PDF..."):
                pdf_bytes = create_pdf_document(preview_df, form_type)
                
                min_s = int(preview_df["Min"].min())
                max_s = int(preview_df["Max"].max())
                if form_type in ["Individual Consent", "Consent"]:
                    filename = f"VVF_Media_Consent_{min_s:05d}_{max_s:05d}.pdf"
                elif form_type == "Group Consent":
                    filename = f"VVF_Group_Consent_{min_s:05d}_{max_s:05d}.pdf"
                else:
                    filename = f"VVF_Attendance_{min_s}_{max_s}.pdf"

                st.session_state.pdf_bytes = pdf_bytes
                st.session_state.pdf_filename = filename
                st.success(f"Success! Compiled PDF Asset: {filename}")
        except Exception as e:
            st.error(f"Compilation fault: {e}")

if st.session_state.get("pdf_bytes"):
    st.download_button(
        label=f"📄 Download {st.session_state.pdf_filename}",
        data=st.session_state.pdf_bytes,
        file_name=st.session_state.pdf_filename,
        mime="application/pdf",
        type="primary",
    )

# Email Dispatch
if btn_email:
    if not st.session_state.get("pdf_bytes"):
        st.error("Missing File: Please click '1. Generate PDF Document' first before dispatching.")
    else:
        try:
            with st.spinner("Dispatching email packet via SMTP..."):
                send_dispatch_email(
                    st.session_state.pdf_bytes,
                    st.session_state.pdf_filename,
                    form_type,
                    preview_df,
                    master_df,
                )
            st.success("Email packet dispatched successfully.")
        except Exception as e:
            st.error(f"Email dispatch error: {e}")