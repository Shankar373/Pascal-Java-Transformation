{ P0 fixture — dialect: Delphi/Object Pascal.
  Expected: compiles with FPC in mode delphi. }
unit DelphiClasses;
{$mode delphi}
interface

uses
  SysUtils;

type
  ECalcError = class(Exception);

  TCalculator = class
  private
    FTotal: Currency;
  public
    procedure Add(Amount: Currency);
    procedure RequirePositive(Amount: Currency);
    property Total: Currency read FTotal;
  end;

implementation

procedure TCalculator.RequirePositive(Amount: Currency);
begin
  if Amount <= 0 then
    raise ECalcError.Create('amount must be positive');
end;

procedure TCalculator.Add(Amount: Currency);
begin
  RequirePositive(Amount);
  FTotal := FTotal + Amount;
end;

end.
