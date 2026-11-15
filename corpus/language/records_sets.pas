{ P0 fixture — language: classic records, nested arrays, enumeration, set membership.
  Expected: compiles with FPC in default mode. }
program RecordsSets;
type
  TColor = (clRed, clGreen, clBlue);
  TColorSet = set of TColor;
  TCell = record
    Row, Col: Integer;
    Tag: TColor;
  end;
  TGrid = array[1..3, 1..3] of TCell;
var
  G: TGrid;
  Allowed: TColorSet;
  I, J: Integer;
begin
  Allowed := [clRed, clBlue];
  for I := 1 to 3 do
    for J := 1 to 3 do
    begin
      G[I, J].Row := I;
      G[I, J].Col := J;
      if (I = J) and (TColor(I - 1) in Allowed) then
        G[I, J].Tag := clRed
      else
        G[I, J].Tag := clGreen;
    end;
  writeln('grid tag11=', Ord(G[1, 1].Tag), ' allowed=', Ord(clBlue) in [Ord(clBlue)])
end.
