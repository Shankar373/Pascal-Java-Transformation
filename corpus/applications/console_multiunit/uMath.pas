{ P0 fixture unit — pure functions used by miniapp.dpr. }
unit uMath;
{$mode objfpc}
interface

function Square(X: Integer): Integer;
function SumRange(Lo, Hi: Integer): Integer;

implementation

function Square(X: Integer): Integer;
begin
  Result := X * X;
end;

function SumRange(Lo, Hi: Integer): Integer;
var
  I: Integer;
begin
  Result := 0;
  for I := Lo to Hi do
    Result := Result + I;
end;

end.
