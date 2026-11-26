{ P0 fixture — directives: conditional compilation with $DEFINE/$IFDEF/$ELSE/$ELSEIFDEF.
  Expected: compiles with FPC; feature flag A on, flag B off. }
program DirectiveIfDef;
{$define FEATURE_A}
{$define FEATURE_B}
var
  Mode: string;
begin
  Mode := 'base';
{$ifdef FEATURE_A}
  Mode := Mode + '+A';
{$endif}
{$ifdef FEATURE_B}
  Mode := Mode + '+B';
{$else}
  Mode := Mode + '-B';
{$endif}
  writeln('directives=', Mode)
end.
