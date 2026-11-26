{ P0 fixture — language: string kinds and code-page-sensitive operations.
  Expected: compiles with FPC; AnsiString semantics preserved (Delphi UnicodeString
  generation differences are a documented dialect gap, tested separately). }
program StringKinds;
var
  S: AnsiString;
  Short: ShortString;
  Ch: Char;
  I: Integer;
begin
  S := 'hello';
  S := S + ' world';
  Short := 'abc';
  Ch := S[1];
  writeln('strlen=', Length(S), ' first=', Ch, ' shortlen=', Length(Short));
  for I := 1 to Length(Short) do
    write(Short[I]);
  writeln
end.
