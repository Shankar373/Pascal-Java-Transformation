{ P0 fixture — dialect: ISO 7185-style Standard Pascal subset.
  No Object Pascal features. Expected: compiles with FPC under -Miso or -Mtp. }
program HelloIso;
var
  Total: Integer;
begin
  Total := 40 + 2;
  writeln('iso7185 total=', Total)
end.
