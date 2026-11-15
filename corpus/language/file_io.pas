{ P0 fixture — language: TextFile I/O with explicit path from ParamStr.
  Harness passes a temp path; file bytes/encoding are a differential-test target. }
program FileIO;
{$mode objfpc}
var
  F: TextFile;
  Line: string;
  OutPath: string;
begin
  if ParamCount < 1 then
  begin
    writeln('usage: file_io <outfile>');
    Halt(1);
  end;
  OutPath := ParamStr(1);
  AssignFile(F, OutPath);
  Rewrite(F);
  writeln(F, 'line one');
  writeln(F, 'line two');
  CloseFile(F);

  AssignFile(F, OutPath);
  Reset(F);
  while not Eof(F) do
  begin
    Readln(F, Line);
    writeln('read=', Line);
  end;
  CloseFile(F)
end.
