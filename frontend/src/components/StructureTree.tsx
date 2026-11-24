import { useState } from "react";
import type { ReactElement } from "react";
import { fmt } from "../format";
import { Icon } from "../icons";
import type { StructureNode } from "../types";
import { Panel } from "./Panel";

function nodeLabel(node: StructureNode): string {
  const files = node.counts && typeof node.counts.files === "number" ? node.counts.files : null;
  return node.kind === "group" && files !== null ? `${node.name} (${fmt(files)})` : node.name;
}

function TreeItem({ node, depth }: { node: StructureNode; depth: number }): ReactElement {
  const [open, setOpen] = useState(depth < 1);
  const kids = Array.isArray(node.children) ? node.children : [];
  if (kids.length === 0 && !node.truncated) {
    const folder = node.kind === "group" || node.kind === "application";
    return (
      <li className="tree-item">
        <span className="tree-leaf">
          <Icon name={folder ? "folder" : "file"} className="tree-icon" />
          <span className="tree-label">{nodeLabel(node)}</span>
        </span>
      </li>
    );
  }
  return (
    <li className="tree-item">
      <button type="button" className="tree-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="right" className="tree-caret" />
        <Icon name="folder" className="tree-icon" />
        <span className="tree-label">{nodeLabel(node)}</span>
      </button>
      <ul className="tree-children" hidden={!open}>
        {kids.map((k, i) => <TreeItem key={i} node={k} depth={depth + 1} />)}
        {node.truncated ? <li className="tree-more">More items not shown</li> : null}
      </ul>
    </li>
  );
}

export function StructurePanel({ root }: { root: StructureNode | null | undefined }): ReactElement {
  const top = root && Array.isArray(root.children) && root.children.length === 1 && root.children[0]
    ? root.children[0]
    : root;
  return (
    <Panel title="Application Structure" icon="tree" cls="area-tree">
      <ul className="tree">
        {top ? <TreeItem node={top} depth={0} /> : <li className="muted">No structure available.</li>}
      </ul>
    </Panel>
  );
}
