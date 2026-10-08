import Lean

/- Native mark-and-sweep over compiled and resolved-source dependencies.
Generated constants remain graph vertices; only authored declarations are pruning units. -/
namespace TidyLean.Orphans
open Lean

structure Node where
  name : String
  module : String
  kind : String
  proof : Bool
  line : Nat
  authored : Bool := false
  dependencies : Array String := #[]
  source_dependencies : Array String := #[]
  deriving FromJson, Inhabited

structure Input where
  nodes : Array Node
  modules : Array String
  paper_roots : Array String
  source_modules : Array String
  exceptions : Json := Json.mkObj []
  deriving FromJson

abbrev Names := Std.HashSet String
abbrev Graph := Std.HashMap String Node

def sorted (names : Array String) : Array String :=
  (names.foldl (fun (seen : Names) name => seen.insert name) {}).toArray.qsort (· < ·)

def object (entries : Array (String × Json)) : Json := Json.mkObj entries.toList

def mark (graph : Graph) (roots : Array String) : Names := Id.run do
  let mut marked : Names := {}
  let mut pending := roots.toList
  while !pending.isEmpty do
    match pending with
    | [] => break
    | name :: rest =>
      pending := rest
      if marked.contains name then continue
      if let some node := graph[name]? then
        marked := marked.insert name
        pending := node.dependencies.toList ++ pending
  return marked

/-- Exception groups stay explicit and require nonempty human reasons. -/
def exceptions (value : Json) : Except String (Array (String × String) × Array (String × String)) := do
  let fields ← value.getObj?
  for (key, _) in fields.toArray do
    unless key == "roots" || key == "modules" do
      throw "orphan exceptions must contain only roots and modules"
  let group (key : String) : Except String (Array (String × String)) := do
    let entries ← (fields[key]?.getD (Json.mkObj [])).getObj?
    entries.toArray.mapM fun (name, reason) => do
      let text ← reason.getStr?
      if text.trimAscii.toString.isEmpty then
        throw "orphan exceptions require names and nonempty reasons"
      return (name, text)
  return (← group "roots", ← group "modules")

/-- Mark from paper roots, separately mark exceptional retention roots, and
classify the authored remainder. Incoming edges never count as paper support. -/
def audit (input : Input) : Except String Json := do
  let (retainedRoots, retainedModules) ← exceptions input.exceptions
  let mut graph : Graph := {}
  for node in input.nodes do
    if graph.contains node.name then throw s!"duplicate Lean declaration: {node.name}"
    graph := graph.insert node.name node
  let linked := mark graph input.paper_roots
  let mut connected := linked
  for name in (mark graph (retainedRoots.map Prod.fst)).toArray do
    connected := connected.insert name
  let mut errors : Array String := #[]
  for (name, _) in retainedRoots do
    match graph[name]? with
    | none => errors := errors.push s!"orphan-roots.json: unknown standalone declaration {name}"
    | some node =>
      if !node.authored then
        errors := errors.push s!"orphan-roots.json: standalone root is not authored: {name}"
      else if linked.contains name then
        errors := errors.push s!"orphan-roots.json: redundant standalone root {name}"
  for (name, _) in retainedModules do
    if !input.source_modules.contains name then
      errors := errors.push s!"orphan-roots.json: unknown excluded source module {name}"
    else if input.modules.contains name then
      errors := errors.push s!"orphan-roots.json: redundant imported-module exclusion {name}"
  let declarations := sorted ((input.nodes.filter (·.authored)).map (·.name))
  let proofs := declarations.filter fun name => (graph[name]!).proof
  let orphans := declarations.filter fun name => !linked.contains name
  let orphanProofs := orphans.filter fun name => (graph[name]!).proof
  let mut dependents : Std.HashMap String Names := {}
  for node in input.nodes do
    for dependency in node.dependencies do
      if dependency != node.name && graph.contains dependency then
        dependents := dependents.insert dependency
          ((dependents[dependency]?.getD {}).insert node.name)
  let missing := sorted (input.source_modules.filter fun name => !input.modules.contains name)
  let orphanModules := sorted ((orphans.filter fun name => !connected.contains name).map
    fun name => (graph[name]!).module)
  for moduleName in orphanModules do
    let names := orphans.filter fun name =>
      !connected.contains name && (graph[name]!).module == moduleName
    let preview := String.intercalate ", " (names.toList.take 5)
    let suffix := if names.size > 5 then s!", ... ({names.size} total)" else ""
    errors := errors.push s!"{moduleName}: orphaned Lean declarations: {preview}{suffix}"
  for moduleName in missing do
    if !(retainedModules.map Prod.fst).contains moduleName then
      errors := errors.push s!"{moduleName}: source module is not imported by DeadlockProofs; declaration coverage unknown"
  let unused := orphans.filter fun name => (dependents[name]?.getD {}).isEmpty
  let allNames := sorted (input.nodes.map (·.name))
  return Json.mkObj [
    ("paper_connected", toJson (sorted linked.toArray)),
    ("standalone_connected", toJson (sorted (connected.toArray.filter fun n => !linked.contains n))),
    ("declaration_inventory", toJson declarations),
    ("declaration_kinds", object (declarations.map fun n => (n, toJson (graph[n]!).kind))),
    ("proof_inventory", toJson proofs),
    ("orphaned_declarations", toJson orphans),
    ("orphaned_proofs", toJson orphanProofs),
    ("unimported_modules", toJson missing),
    ("unused_orphaned_declarations", toJson unused),
    ("unused_orphaned_proofs", toJson (unused.filter fun n => (graph[n]!).proof)),
    ("retained_orphans", toJson (orphans.filter connected.contains)),
    ("orphan_dependents", object (orphans.map fun n =>
      (n, toJson (sorted (dependents[n]?.getD {}).toArray)))),
    ("dependencies", object (allNames.map fun n => (n, toJson (sorted (graph[n]!).dependencies)))),
    ("source_dependencies", object ((allNames.filter fun n => !(graph[n]!).source_dependencies.isEmpty).map
      fun n => (n, toJson (sorted (graph[n]!).source_dependencies)))),
    ("orphan_locations", object (orphans.map fun n =>
      (n, Json.mkObj [("module", toJson (graph[n]!).module), ("line", toJson (graph[n]!).line)]))),
    ("exceptions", Json.mkObj [
      ("roots", object (retainedRoots.map fun (n, r) => (n, toJson r))),
      ("modules", object (retainedModules.map fun (n, r) => (n, toJson r)))]),
    ("errors", toJson errors)]

end TidyLean.Orphans

def main (args : List String) : IO UInt32 := do
  let [path] := args | throw (IO.userError "expected an audit input JSON path")
  let text ← IO.FS.readFile path
  let result := do
    let json ← Lean.Json.parse text
    let input ← Lean.fromJson? (α := TidyLean.Orphans.Input) json
    TidyLean.Orphans.audit input
  let (output, status) := match result with
    | .ok report => (Lean.Json.mkObj [("report", report)], 0)
    | .error message => (Lean.Json.mkObj [("error", Lean.toJson message)], 1)
  IO.println ("@@ORPHAN_AUDIT " ++ output.compress)
  return UInt32.ofNat status
