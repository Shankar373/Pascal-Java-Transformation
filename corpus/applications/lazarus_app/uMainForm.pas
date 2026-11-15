{ P0 fixture — Lazarus form unit for discovery tests.
  FAIL-DEPENDENCY expected when LCL is absent (Forms/Controls units). }
unit uMainForm;
{$mode objfpc}
interface

uses
  Classes, SysUtils, Forms, Controls, StdCtrls;

type
  TMainForm = class(TForm)
    Button1: TButton;
    procedure Button1Click(Sender: TObject);
  end;

var
  MainForm: TMainForm;

implementation

procedure TMainForm.Button1Click(Sender: TObject);
begin
  Caption := 'clicked';
end;

end.
