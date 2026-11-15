{ P0 fixture — language: exceptions, try/except/finally, exit codes, Halt.
  Expected: compiles with FPC; error-path behavior is a differential-test oracle target. }
program ExceptionFlow;
{$mode objfpc}

uses
  SysUtils;

type
  EBadInput = class(Exception);
procedure Validate(V: Integer);
begin
  if V < 0 then
    raise EBadInput.Create('negative');
end;
var
  Code: Integer;
begin
  Code := 0;
  try
    try
      Validate(-1);
    except
      on E: EBadInput do
      begin
        writeln('caught=', E.Message);
        Code := 2;
      end;
    end;
  finally
    writeln('cleanup');
  end;
  if Code <> 0 then
    Halt(Code);
  writeln('unreachable')
end.
