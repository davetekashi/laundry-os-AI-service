import json
import subprocess
from pathlib import Path


COLLECTIONS = [
    "laundries",
    "laundrybankaccounts",
    "laundrycustomers",
    "laundrydebts",
    "laundrymembers",
    "laundrywallets",
    "logisticsjobs",
    "customerpayments",
    "orders",
]


def load_mongo_uri() -> str:
    env_path = Path(".env")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MONGODB_URI="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("MONGODB_URI not found in .env")


def build_mongosh_script() -> str:
    collections_json = json.dumps(COLLECTIONS)
    return f"""
const collections = {collections_json};

function describe(value) {{
  if (value === null) return "null";
  if (Array.isArray(value)) {{
    if (value.length === 0) return [];
    return [describe(value[0])];
  }}
  if (value instanceof Date) return "date";
  if (value && value._bsontype === "ObjectId") return "objectId";
  if (value && value._bsontype === "Decimal128") return "decimal128";
  if (value && typeof value === "object") {{
    const out = {{}};
    for (const [key, nested] of Object.entries(value)) {{
      out[key] = describe(nested);
    }}
    return out;
  }}
  return typeof value;
}}

const result = {{}};
for (const name of collections) {{
  const coll = db.getCollection(name);
  const docs = coll.find({{}}, {{ _id: 0 }}).limit(3).toArray();
  result[name] = {{
    count: coll.countDocuments(),
    sampleCount: docs.length,
    structures: docs.map(describe)
  }};
}}

print(JSON.stringify(result, null, 2));
"""


def main() -> None:
    mongo_uri = load_mongo_uri()
    script = build_mongosh_script()
    completed = subprocess.run(
        ["mongosh", mongo_uri, "--quiet", "--eval", script],
        text=True,
        capture_output=True,
        check=True,
    )
    print(completed.stdout)


if __name__ == "__main__":
    main()
