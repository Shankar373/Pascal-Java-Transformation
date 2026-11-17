"""Stage 1 integration detector (`p1.integrations.detect_integrations`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from p1.findings import INTEGRATION_CATEGORIES
from p1.integrations import detect_integrations
from s1helpers import (
    SECRET,
    analyse,
    assert_well_formed,
    dump_all,
    enterprise,
    pas,
)


@pytest.fixture(scope="module")
def ent(tmp_path_factory):
    return enterprise(tmp_path_factory)


def _run(tmp_path: Path, files: dict) -> dict:
    estate = analyse(tmp_path / "t", files)
    found = detect_integrations(estate.analysed, estate.text_of)
    assert_well_formed(found)
    return {(f.category, f.technology): f for f in found}


# --------------------------------------------------------------------------
# fixture application
# --------------------------------------------------------------------------


def _fixture(ent) -> dict:
    return {(f.category, f.technology): f
            for f in detect_integrations(ent.analysed, ent.text_of)}


def test_fixture_indy_http_endpoint(ent) -> None:
    found = _fixture(ent)[("http-client", "Indy")]
    assert "https://api.example.com/v1/orders" in found.endpoints
    assert {e.file for e in found.evidence} == {"src/uHttpClient.pas"}
    assert found.confidence == "high"
    assert found.status == "PARTIAL"


def test_fixture_soap_billing_endpoint(ent) -> None:
    found = _fixture(ent)[("soap-webservice", "SOAP")]
    assert ("http://billing.corp.example.com:8080/BillingService.asmx"
            in found.endpoints)
    assert any(e.file == "src/uSoapClient.pas" for e in found.evidence)


def test_fixture_ftp_and_smtp_hosts(ent) -> None:
    found = _fixture(ent)
    assert "ftp.partner.example.org" in found[("ftp", "Indy")].endpoints
    assert "smtp.corp.example.com" in found[("email", "Indy")].endpoints
    assert "smtp.corp.example.com" not in found[("ftp", "Indy")].endpoints


def test_fixture_com_service_reporting(ent) -> None:
    found = _fixture(ent)
    assert "Excel.Application" in found[("com-ole", "COM/OLE")].endpoints
    assert ("windows-service", "TService") in found
    assert any(e.file == "src/uTransfer.pas" for e in
               found[("windows-service", "TService")].evidence)
    assert ("reporting", "FastReport") in found


def test_fixture_is_well_formed_vocabulary_and_secret_free(ent) -> None:
    found = detect_integrations(ent.analysed, ent.text_of)
    assert_well_formed(found)
    assert all(f.category in INTEGRATION_CATEGORIES for f in found)
    assert SECRET not in dump_all(found)
    assert not any("S3cr3t" in str(e) for f in found for e in f.endpoints)


def test_fixture_deterministic_under_shuffle(ent) -> None:
    base = dump_all(detect_integrations(ent.analysed, ent.text_of))
    for seed in (7, 8, 9):
        again = detect_integrations(ent.shuffled(seed), ent.text_of)
        assert dump_all(again) == base


# --------------------------------------------------------------------------
# technologies
# --------------------------------------------------------------------------


def test_synapse_units(tmp_path: Path) -> None:
    found = _run(tmp_path, {"a.pas": pas(
        "a", "SysUtils, httpsend, ftpsend, synaser, smtpsend, ldapsend")})
    for key in (("http-client", "Synapse"), ("ftp", "Synapse"),
                ("serial-port", "Synapse"), ("email", "Synapse"),
                ("ldap", "Synapse")):
        assert key in found, sorted(found)
    assert found[("http-client", "Synapse")].confidence == "medium"


def test_ics_wininet_winsock(tmp_path: Path) -> None:
    found = _run(tmp_path, {
        "a.pas": pas("a", "OverbyteIcsHttpProt, OverbyteIcsWSocket"),
        "b.pas": pas("b", "Windows, WinInet", "procedure P; begin "
                     "InternetOpen(nil, 0, nil, nil, 0); end;"),
        "c.pas": pas("c", "Winsock, ssockets"),
    })
    assert ("http-client", "ICS") in found and ("socket", "ICS") in found
    assert ("http-client", "WinInet") in found
    assert ("socket", "Winsock") in found
    assert any(t == "ssockets" for c, t in found if c == "socket")


def test_http_server_messaging_ldap_printing_serial(tmp_path: Path) -> None:
    found = _run(tmp_path, {
        "a.pas": pas("a", "IdHTTPServer, mqtt, Printers, CPort, winldap",
                     "var C: TMQTTClient; P: TComPort;"),
    })
    assert ("http-server", "Indy") in found
    assert ("messaging", "MQTT") in found
    assert ("printing", "Printers") in found
    assert ("serial-port", "ComPort Library") in found
    assert ("ldap", "Windows LDAP") in found
    assert found[("messaging", "MQTT")].confidence == "high"


def test_dcom_remote_object_and_progids(tmp_path: Path) -> None:
    body = (
        "procedure P;\nbegin\n"
        "  O := CreateRemoteComObject('SRV01', CLASS_Foo);\n"
        "  W := CreateOleObject('Word.Application');\n"
        "  X := CreateOleObject('MSXML2.ServerXMLHTTP.6.0');\n"
        "  M := CreateOleObject('Outlook.Application');\n"
        "end;")
    found = _run(tmp_path, {"a.pas": pas("a", "ComObj, ActiveX", body)})
    assert "SRV01" in found[("dcom", "DCOM")].endpoints
    assert "Word.Application" in found[("com-ole", "COM/OLE")].endpoints
    assert ("http-client", "MSXML") in found
    assert ("email", "Outlook (COM)") in found


def test_reporting_and_scheduled_jobs(tmp_path: Path) -> None:
    found = _run(tmp_path, {
        "a.pas": pas("a", "QuickRpt, QRCtrls", "var R: TQuickRep;"),
        "q.pas": pas("q", "QRCodeGen"),
        "r.bat": "schtasks /create /tn Nightly /tr run.bat /sc daily\n",
        "etc/crontab": "0 2 * * * /usr/bin/job\n",
        "job.sql": "BEGIN DBMS_SCHEDULER.CREATE_JOB(job_name => 'J'); END;\n",
        "rep/Sales.fr3": "<?xml version=\"1.0\"?><TfrxReport/>",
    })
    assert ("reporting", "QuickReport") in found
    assert ("reporting", "FastReport") in found  # .fr3 template file
    assert ("scheduled-job", "schtasks") in found
    assert ("scheduled-job", "cron") in found
    assert ("scheduled-job", "SQL scheduler") in found
    quick = found[("reporting", "QuickReport")]
    assert {e.file for e in quick.evidence} == {"a.pas"}  # QRCodeGen is not QR


def test_dfm_components_and_properties(tmp_path: Path) -> None:
    dfm = (
        "object Form1: TForm1\n"
        "  object Http: TIdHTTP\n"
        "    Left = 8\n"
        "  end\n"
        "  object Ftp: TIdFTP\n"
        "    Host = 'ftp.dfm.example.org'\n"
        "    Port = 2121\n"
        "  end\n"
        "  object Rio: THTTPRIO\n"
        "    URL = 'http://svc.dfm.example.org/Svc.asmx'\n"
        "  end\n"
        "end\n"
    )
    found = _run(tmp_path, {"f.dfm": dfm})
    assert "ftp.dfm.example.org:2121" in found[("ftp", "Indy")].endpoints
    assert "http://svc.dfm.example.org/Svc.asmx" in \
        found[("soap-webservice", "SOAP")].endpoints
    assert ("http-client", "Indy") in found
    assert found[("ftp", "Indy")].confidence == "low"  # classes only
    assert all(e.file == "f.dfm" for e in found[("ftp", "Indy")].evidence)


def test_host_port_pairing_uses_variable_types(tmp_path: Path) -> None:
    body = (
        "procedure P;\nvar Smtp: TIdSMTP; Pop: TIdPOP3;\nbegin\n"
        "  Smtp.Host := 'mail.out.example.org';\n"
        "  Smtp.Port := 587;\n"
        "  Pop.Host := 'mail.in.example.org';\n"
        "end;")
    found = _run(tmp_path, {"a.pas": pas("a", "IdSMTP, IdPOP3", body)})
    ends = found[("email", "Indy")].endpoints
    assert "mail.out.example.org:587" in ends
    assert "mail.in.example.org" in ends


# --------------------------------------------------------------------------
# negatives
# --------------------------------------------------------------------------


def test_names_in_comments_and_strings_do_not_trigger(tmp_path: Path) -> None:
    src = (
        "unit a;\ninterface\nuses SysUtils;\nimplementation\n"
        "{ uses IdHTTP, httpsend, ComObj; TIdHTTP }\n"
        "(* uses IdFTP *)\n"
        "// var X: TIdSMTP; CreateOleObject\n"
        "const S = 'uses IdHTTP; TIdHTTP SOAPHTTPClient frxClass';\n"
        "var idhttp: Integer;\n"
        "end.\n"
    )
    found = _run(tmp_path, {"a.pas": src})
    assert found == {}


def test_urls_namespaces_and_fragments(tmp_path: Path) -> None:
    src = pas("a", "SysUtils", (
        "const\n"
        "  A = 'http://www.w3.org/2001/XMLSchema';\n"
        "  B = 'http://schemas.xmlsoap.org/soap/envelope/';\n"
        "  C = 'http://';\n"
        "  D = 'https://%s/api';\n"
        "  E = 'https://shop.example.com/api';\n"
        "  F = 'ftp://bob:p4ssw0rd@files.example.com/in?token=ZZZ#frag';\n"
        "  G = 'https://x.example.com/a?api_key=SECRETKEY123&b=2';\n"))
    found = _run(tmp_path, {"a.pas": src})
    urls = set(found[("http-client", "URL literal")].endpoints)
    assert urls == {"https://shop.example.com/api",
                    "https://x.example.com/a"}
    assert found[("ftp", "URL literal")].endpoints == (
        "ftp://files.example.com/in",)
    assert found[("http-client", "URL literal")].confidence == "low"
    dumped = dump_all(list(found.values()))
    for leaked in ("p4ssw0rd", "SECRETKEY123", "ZZZ"):
        assert leaked not in dumped


def test_password_literal_is_never_emitted(tmp_path: Path) -> None:
    src = pas("a", "IdHTTP", (
        "procedure P; var H: TIdHTTP; begin\n"
        f"  H.Request.Password := '{SECRET}';\n"
        f"  H.Get('https://u:{SECRET}@api.example.com/x');\n"
        "end;"))
    found = _run(tmp_path, {"a.pas": src})
    assert SECRET not in dump_all(list(found.values()))
    assert "https://api.example.com/x" in found[("http-client", "Indy")].endpoints


# --------------------------------------------------------------------------
# adversarial
# --------------------------------------------------------------------------


def test_endpoint_and_evidence_caps(tmp_path: Path) -> None:
    consts = "\n".join(
        f"  U{i} = 'https://h{i:03d}.example.com/p';" for i in range(120))
    src = pas("a", "IdHTTP", f"const\n{consts}\n")
    found = _run(tmp_path, {"a.pas": src})
    finding = found[("http-client", "Indy")]
    assert len(finding.endpoints) == 20
    assert len(finding.evidence) == 25
    assert finding.endpoints == tuple(sorted(finding.endpoints))[:20] or \
        len(set(finding.endpoints)) == 20


def test_ten_thousand_identical_references_stay_bounded(
        tmp_path: Path) -> None:
    body = "begin\n" + "  H := TIdHTTP.Create(nil);\n" * 10_000 + "end;"
    found = _run(tmp_path, {"a.pas": pas("a", "IdHTTP", body)})
    finding = found[("http-client", "Indy")]
    assert len(finding.evidence) <= 25


def test_garbage_unterminated_and_huge_inputs(tmp_path: Path) -> None:
    found = _run(tmp_path, {
        "bin.pas": bytes(range(256)) * 400,
        "open.pas": "unit open; interface uses IdHTTP; implementation\n"
                    "const S = 'https://never.example.com/closed\n"
                    "{ unterminated comment",
        "big.pas": pas("big", "SysUtils", "// " + "x" * 3_000_000),
        "bad.dfm": "object X: TIdHTTP\n  Host = 'unterminated\n" * 500,
    })
    assert ("http-client", "Indy") in found


def test_shuffle_determinism_on_synthetic_tree(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        f"u{i}.pas": pas(f"u{i}", "IdHTTP, IdFTP",
                         f"const U = 'https://h{i}.example.com/';")
        for i in range(12)
    })
    base = dump_all(detect_integrations(estate.analysed, estate.text_of))
    for seed in (1, 2, 3):
        assert dump_all(
            detect_integrations(estate.shuffled(seed), estate.text_of)
        ) == base


def test_queue_com_port_and_unc_literals(tmp_path: Path) -> None:
    body = (
        "const\n"
        "  Q1 = '.\\private$\\orders';\n"
        "  Q2 = 'FormatName:DIRECT=OS:srv\\private$\\jobs';\n"
        "  P = 'COM3';\n"
        "  S = '\\\\fileserver\\share\\inbox\\x';\n"
        "  N = 'COMMON';\n"
    )
    found = _run(tmp_path, {"a.pas": pas("a", "SysUtils", body)})
    queues = found[("messaging", "MSMQ")].endpoints
    assert ".\\private$\\orders" in queues
    assert any(q.startswith("FormatName:") for q in queues)
    assert found[("serial-port", "Serial port literal")].endpoints == ("COM3",)
    assert found[("file-exchange", "UNC share")].endpoints == (
        "\\\\fileserver\\share",)


def test_pathological_lines_do_not_blow_up(tmp_path: Path) -> None:
    import time

    nasty = ("a-" * 1000 + "\n") * 2000
    estate = analyse(tmp_path / "t", {
        "x.cfg": nasty, "y.bat": nasty, "z.ini": nasty,
        "a.pas": pas("a", "IdHTTP", "// " + "-password=" * 400),
    })
    started = time.perf_counter()
    detect_integrations(estate.analysed, estate.text_of)
    assert time.perf_counter() - started < 10
