{ P0 fixture — dialect: Free Pascal mode objfpc, with class type.
  Expected: compiles with FPC default/objfpc mode. }
program ModeObjFpc;
{$mode objfpc}{$H+}
type
  TCounter = class
  private
    FValue: Integer;
  public
    constructor Create(AValue: Integer);
    function Increment: Integer;
  end;

constructor TCounter.Create(AValue: Integer);
begin
  FValue := AValue;
end;

function TCounter.Increment: Integer;
begin
  Inc(FValue);
  Result := FValue;
end;

var
  C: TCounter;
begin
  C := TCounter.Create(41);
  try
    writeln('objfpc counter=', C.Increment);
  finally
    C.Free;
  end;
end.
