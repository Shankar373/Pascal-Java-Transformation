{ P0 fixture — dialect: Turbo Pascal subset.
  Expected: compiles with FPC -Mtp (TP/BP 7.0 compatibility mode). }
program TurboPoint;
type
  TPointRec = record
    X, Y: Integer;
  end;
var
  P: TPointRec;
begin
  P.X := 3;
  P.Y := 4;
  writeln('tp point=', P.X, ',', P.Y)
end.
