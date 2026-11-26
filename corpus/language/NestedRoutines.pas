{ P0 fixture — language: nested procedures capturing outer scope (Delphi/FPC feature).
  Expected: compiles with FPC -Mdelphi; nested scope resolution is an IR requirement. }
unit NestedRoutines;
{$mode delphi}
interface

function OuterSum(A, B: Integer): Integer;

implementation

function OuterSum(A, B: Integer): Integer;
var
  Total: Integer;

  procedure Add(X: Integer);
  begin
    Total := Total + X;    { captures OuterSum scope }
  end;

begin
  Total := 0;
  Add(A);
  Add(B);
  Result := Total;
end;

end.
