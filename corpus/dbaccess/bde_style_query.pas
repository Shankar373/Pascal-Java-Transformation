{ P0 fixture — database access: legacy BDE-style component usage.
  FAIL-DEPENDENCY expected: unit 'DB' (or 'DBTables') is unavailable under plain FPC.
  Proves dependency discovery of legacy data-access frameworks. }
program BdeStyleQuery;
uses
  DB, DBTables;
var
  Q: TQuery;
begin
  Q := TQuery.Create(nil);
  try
    Q.SQL.Text := 'SELECT * FROM orders WHERE status = ''OPEN''';
    Q.Open;
    writeln('rows=', Q.RecordCount);
  finally
    Q.Free;
  end;
end.
