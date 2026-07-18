.metadata.deletionTimestamp == null
and (.spec | keys | sort) == ["egress", "podSelector", "policyTypes"]
and (.spec.podSelector | keys | sort) == ["matchLabels"]
and .spec.podSelector.matchLabels == {
  "app.kubernetes.io/component": "safety-controller",
  "app.kubernetes.io/name": "faz22-view-only-pilot-watchdog"
}
and (.spec.policyTypes | sort) == ["Egress"]
and (.spec.egress | length) == 2
and all(.spec.egress[];
  (. | keys | sort) == ["ports", "to"]
  and (.to | length) == 1
  and (.ports | length) == 1
  and (.to[0] | keys | sort) == ["ipBlock"]
  and (.to[0].ipBlock | keys | sort) == ["cidr"]
  and (.ports[0] | keys | sort) == ["port", "protocol"]
)
and ([.spec.egress[] | {
  cidr: .to[0].ipBlock.cidr,
  protocol: .ports[0].protocol,
  port: .ports[0].port
}] | sort_by(.cidr)) == ([
  {cidr: "10.45.0.1/32", protocol: "TCP", port: 443},
  {cidr: "172.19.0.0/16", protocol: "TCP", port: 6443}
] | sort_by(.cidr))
