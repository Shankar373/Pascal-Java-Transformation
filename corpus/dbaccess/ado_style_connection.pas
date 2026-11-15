{ P0 fixture — database access: ADO/COM-style connection usage.
  Expected: FAIL-DEPENDENCY on non-Windows (unit ComObj is absent there); on
  Windows FPC it compiles (compile-only - no ADO provider is registered, so the
  runtime path is not exercised here).
  Proves native/COM dependency discovery. }
program AdoStyleConnection;
uses
  ComObj, Variants;
var
  Conn: Variant;
begin
  Conn := CreateOleObject('ADODB.Connection');
  Conn.ConnectionString := 'Provider=SQLOLEDB;Data Source=legacy;Initial Catalog=sales;';
  Conn.Open;
  writeln('ado-opened');
  Conn.Close;
end.
