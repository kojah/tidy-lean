import Lean

/-!
`#paper_dump n₁ n₂ …` prints, for each declaration, the facts the paper
check (`check_paper.py`) compares against its lock file: the declaration's
statement as Lean prints it, the module and lines it is declared at, and
the axioms it depends on. A missing name is reported, not an error, so one
run lists every problem.
-/

open Lean Elab Command Meta

elab "#paper_dump " ns:ident* : command => do
  for n in ns do
    let name := n.getId
    let env ← getEnv
    match env.find? name with
    | none => logInfo m!"@@MISSING {name}"
    | some ci =>
      let ty ← liftTermElabM <| ppExpr ci.type
      let axs ← liftCoreM <| collectAxioms name
      let mod := match env.getModuleIdxFor? name with
        | some i => env.header.moduleNames[i.toNat]!
        | none => Name.anonymous
      let lines ← match ← findDeclarationRanges? name with
        | some r => pure s!"{r.range.pos.line}-{r.range.endPos.line}"
        | none => pure "?"
      logInfo m!"@@DECL {name}\n@@KIND {if ci.isThm then "theorem" else "definition"}\n@@AT {mod} {lines}\n@@AXIOMS {axs.toList}\n@@TYPE\n{ty}\n@@END"

/- The dependency inventory includes definition and proof bodies, not just
theorem statements. Generated declarations remain graph intermediates. -/
elab "#paper_inventory" : command => do
  let env ← getEnv
  let modules := env.header.moduleNames.filter fun name =>
    name.toString == "DeadlockProofs" || name.toString.startsWith "DeadlockProofs."
  logInfo m!"@@INVENTORY_BEGIN {Json.compress (toJson (modules.map Name.toString))}"
  for (name, ci) in env.constants.toList do
    let some index := env.getModuleIdxFor? name | continue
    let moduleName := env.header.moduleNames[index.toNat]!
    if !modules.contains moduleName then continue
    let ranges ← findDeclarationRanges? name
    let dependencies := ci.getUsedConstantsAsSet.toList.map Name.toString
    let record := Json.mkObj [
      ("name", toJson name.toString),
      ("module", toJson moduleName.toString),
      ("kind", toJson (if ci.isThm then "theorem" else if isStructure env name then "structure"
        else if ci.isInductive then "inductive" else "definition")),
      ("dependencies", toJson dependencies),
      ("proof", toJson (ci.isThm && ranges.isSome && !(privateToUserName name).isInternalDetail)),
      ("line", toJson ((ranges.map fun r => r.range.pos.line).getD 0))]
    logInfo m!"@@NODE {record.compress}"
  logInfo m!"@@INVENTORY_END"
