# REA for game save analysis: raises the managed (.NET) metadata representation
# budget so large Unity Assembly-CSharp.dll files can be inspected.
FROM mcp/rea:latest
RUN sed -i 's/const MAX_METADATA_REPRESENTATION_BYTES = 64 \* 1024 \* 1024;/const MAX_METADATA_REPRESENTATION_BYTES = 1024 * 1024 * 1024;/' \
      /usr/local/lib/node_modules/rea-agents/dist/dotnet/ManagedDecodeBudget.js \
 && grep -q "1024 \* 1024 \* 1024" /usr/local/lib/node_modules/rea-agents/dist/dotnet/ManagedDecodeBudget.js
ENV NODE_OPTIONS=--max-old-space-size=8192
