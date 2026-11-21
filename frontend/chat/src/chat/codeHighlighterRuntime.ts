// The syntax highlighter for code blocks, loaded on first use with its themes and the registered languages.

import type { ComponentType, ReactNode } from "react";

export type SyntaxHighlighterComponent = ComponentType<{
  language?: string;
  style?: unknown;
  customStyle?: Record<string, string | number>;
  PreTag?: keyof JSX.IntrinsicElements | ComponentType<unknown>;
  children?: ReactNode;
}>;

export type CodeHighlighterRuntime = {
  SyntaxHighlighter: SyntaxHighlighterComponent;
  oneDark: unknown;
  oneLight: unknown;
};

let codeHighlighterRuntimePromise: Promise<CodeHighlighterRuntime> | null =
  null;

export function loadCodeHighlighterRuntime() {
  if (!codeHighlighterRuntimePromise) {
    codeHighlighterRuntimePromise = Promise.all([
      import("react-syntax-highlighter/dist/esm/prism-light"),
      import("react-syntax-highlighter/dist/esm/styles/prism"),
      import("react-syntax-highlighter/dist/esm/languages/prism/bash"),
      import("react-syntax-highlighter/dist/esm/languages/prism/css"),
      import("react-syntax-highlighter/dist/esm/languages/prism/diff"),
      import("react-syntax-highlighter/dist/esm/languages/prism/docker"),
      import("react-syntax-highlighter/dist/esm/languages/prism/go"),
      import("react-syntax-highlighter/dist/esm/languages/prism/graphql"),
      import("react-syntax-highlighter/dist/esm/languages/prism/java"),
      import("react-syntax-highlighter/dist/esm/languages/prism/javascript"),
      import("react-syntax-highlighter/dist/esm/languages/prism/jsx"),
      import("react-syntax-highlighter/dist/esm/languages/prism/json"),
      import("react-syntax-highlighter/dist/esm/languages/prism/kotlin"),
      import("react-syntax-highlighter/dist/esm/languages/prism/markdown"),
      import("react-syntax-highlighter/dist/esm/languages/prism/powershell"),
      import("react-syntax-highlighter/dist/esm/languages/prism/python"),
      import("react-syntax-highlighter/dist/esm/languages/prism/rust"),
      import("react-syntax-highlighter/dist/esm/languages/prism/sql"),
      import("react-syntax-highlighter/dist/esm/languages/prism/tsx"),
      import("react-syntax-highlighter/dist/esm/languages/prism/typescript"),
      import("react-syntax-highlighter/dist/esm/languages/prism/xml-doc"),
      import("react-syntax-highlighter/dist/esm/languages/prism/yaml"),
    ]).then(
      ([
        highlighterModule,
        stylesModule,
        bashModule,
        cssModule,
        diffModule,
        dockerModule,
        goModule,
        graphqlModule,
        javaModule,
        javascriptModule,
        jsxModule,
        jsonModule,
        kotlinModule,
        markdownModule,
        powershellModule,
        pythonModule,
        rustModule,
        sqlModule,
        tsxModule,
        typescriptModule,
        xmlModule,
        yamlModule,
      ]) => {
        const PrismLight =
          highlighterModule.default as SyntaxHighlighterComponent & {
            registerLanguage: (name: string, grammar: unknown) => void;
          };
        const languages: Array<[string, unknown]> = [
          ["bash", bashModule.default],
          ["shell", bashModule.default],
          ["sh", bashModule.default],
          ["css", cssModule.default],
          ["diff", diffModule.default],
          ["docker", dockerModule.default],
          ["dockerfile", dockerModule.default],
          ["go", goModule.default],
          ["graphql", graphqlModule.default],
          ["java", javaModule.default],
          ["javascript", javascriptModule.default],
          ["js", javascriptModule.default],
          ["jsx", jsxModule.default],
          ["json", jsonModule.default],
          ["kotlin", kotlinModule.default],
          ["markdown", markdownModule.default],
          ["md", markdownModule.default],
          ["powershell", powershellModule.default],
          ["ps1", powershellModule.default],
          ["python", pythonModule.default],
          ["py", pythonModule.default],
          ["rust", rustModule.default],
          ["rs", rustModule.default],
          ["sql", sqlModule.default],
          ["tsx", tsxModule.default],
          ["typescript", typescriptModule.default],
          ["ts", typescriptModule.default],
          ["xml", xmlModule.default],
          ["html", xmlModule.default],
          ["svg", xmlModule.default],
          ["yaml", yamlModule.default],
          ["yml", yamlModule.default],
        ];
        for (const [name, grammar] of languages) {
          PrismLight.registerLanguage(name, grammar);
        }
        return {
          SyntaxHighlighter: PrismLight,
          oneDark: stylesModule.oneDark,
          oneLight: stylesModule.oneLight,
        };
      },
    );
  }
  return codeHighlighterRuntimePromise;
}
