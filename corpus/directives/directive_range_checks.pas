{ P0 fixture — directives: range and overflow checking ($R+, $Q+).
  Expected: compiles with FPC; runtime range check is exercised by the harness. }
program DirectiveChecks;
{$R+}{$Q+}
var
  Small: SmallInt;
  Acc: Int64;
begin
  Small := 32000;
  Small := Small + 767;      { lands exactly on SmallInt max (32767): boundary test,
                               so no range error fires and the program exits 0 }
  Acc := 0;
  writeln('checks small=', Small, ' acc=', Acc)
end.
