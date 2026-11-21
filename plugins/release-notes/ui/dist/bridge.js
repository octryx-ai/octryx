// Octryx plugin bridge (contract §4): talk only to the Octryx frame that hosts this iframe.
(function () {
  "use strict";
  var pending = {}, seq = 0, contextWaiters = [], context = null;
  window.addEventListener("message", function (event) {
    if (event.source !== window.parent) return;
    var msg = event.data || {};
    if (msg.v !== 1) return;
    if (msg.type === "context") {
      context = msg.context || {};
      contextWaiters.splice(0).forEach(function (fn) { fn(context); });
      return;
    }
    var waiter = pending[msg.id];
    if (!waiter) return;
    delete pending[msg.id];
    if (msg.error) waiter.reject(msg.error); else waiter.resolve(msg.result);
  });
  window.octryx = {
    context: function () {
      return context ? Promise.resolve(context) : new Promise(function (resolve) { contextWaiters.push(resolve); });
    },
    call: function (method, params) {
      var id = "c" + (++seq);
      return new Promise(function (resolve, reject) {
        pending[id] = { resolve: resolve, reject: reject };
        window.parent.postMessage({ v: 1, id: id, method: method, params: params || {} }, "*");
      });
    },
    resize: function () {
      window.parent.postMessage({ v: 1, type: "resize", height: document.documentElement.scrollHeight }, "*");
    }
  };
  window.parent.postMessage({ v: 1, type: "ready" }, "*");
})();
