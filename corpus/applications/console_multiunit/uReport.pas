{ P0 fixture unit — depends on uMath indirectly through the program uses clause. }
unit uReport;
{$mode objfpc}
interface

function ReportTotal(V: Integer): string;

implementation

uses
  SysUtils;

function ReportTotal(V: Integer): string;
begin
  Result := Format('total=%d', [V]);
end;

end.
