/*
 * Copyright (c) 2011 Google Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may
 * not use this file except in compliance with the License. You may obtain
 * a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
 * License for the specific language governing permissions and limitations under
 * the License.
 */

/**
 * @fileoverview Logic for the Cards Against Hangouts app.
 *
 * @author Amy Unruh    (Google)
 * @author Brett Morgan (Google)
 * @author Nick Johnson (Google)
 */

/*jslint browser: true, unparam: true, sloppy: true, nomen: true, maxlen: 100, indent: 2 */

/**
 * Shared state of the app.
 * @type {Object.<!string, !string>}
 * @private
 */
var state_ = null;

/**
 * Describes the shared state of the object.
 * @type {Object.<!string, Object.<!string, *>>}
 * @private
 */
var metadata_ = null;

/**
 * A list of the participants.
 * @type {Array.<gapi.hangout.Participant>}
 * @private
 */
var participants_ = null;

/**
 * Indicator the Channel API is open
 * @type {boolean}
 * @private
 */
var connected = null;

/**
 * Create required DOM elements and listeners.
 */
function prepareAppDOM() {
  // TODO(brettmorgan): do something
}

/**
 * Renders the app.
 */
function render() {
  // TODO(brettmorgan): do something
}

/**
 * Syncs local copies of shared state with those on the server and renders the
 *     app to reflect the changes.
 * @param {!Array.<Object.<!string, *>>} add Entries added to the shared state.
 * @param {!Array.<!string>} remove Entries removed from the shared state.
 * @param {!Object.<!string, !string>} state The shared state.
 * @param {!Object.<!string, Object.<!string, *>>} metadata Data describing the
 *     shared state.
 */
function onStateChanged(add, remove, state, metadata) {
  state_ = state;
  metadata_ = metadata;
  render();
}

/**
 * Syncs local copy of the participants list with that on the server and renders
 *     the app to reflect the changes.
 * @param {!Array.<gapi.hangout.Participant>} participants The new list of
 *     participants.
 */
function onParticipantsChanged(participants) {
  participants_ = participants;
  render();
}

// channel api management
function onOpened() {
  connected = true;
  window.alert('connected to server');
}

// placeholder - handling a message from the channel
function onMessage(m) {
//alert('received message');
//alert(m.data);
  newMessage = JSON.parse(m.data);
//alert('got here!');

  // todo - fix with real channel message structure
  var result_string = newMessage.content;

  document.getElementById('channel_message').innerHTML = result_string;
};

function getToken(){
  var hangout_id, plus_id;
  
  hangout_id = gapi.hangout.getHangoutId();
  plus_id = gapi.hangout.Participant.id;
  
  $.ajax({
    url: "http://cah-xhack.appspot.com/api/join_game",
    success: function(data){
      openChannel(data.channel_token);
    }
    data: {
      hangout_id: hangout_id,
      plus_id: plus_id
    }
  });
  
};

/**
 * Opens a Channel.
 * @param {string} token
 */
function openChannel(token){
 var channel = new goog.appengine.Channel(token);
 var handler = {
      'onopen': onOpened,
      'onmessage': onMessage,
      'onerror': function() {},
      'onclose': function() {}
   };
 var socket = channel.open(handler);
 socket.onopen = onOpened;
 socket.onmessage = onMessage;     
};


(function () {
  if (gapi && gapi.hangout) {

    var initHangout = function () {
      var initState, initMetadata, added, key, removed, initParticipants;

      prepareAppDOM();

      gapi.hangout.data.addStateChangeListener(onStateChanged);
      gapi.hangout.addParticipantsListener(onParticipantsChanged);

      if (!state_) {
        initState = gapi.hangout.data.getState();
        initMetadata = gapi.hangout.data.getStateMetadata();
        added = [];

        for (key in initMetadata) {
          if (initMetadata.hasOwnProperty(key)) {
            added.push(initMetadata[key]);
          }
        }
        removed = [];
        if (initState && initMetadata) {
          onStateChanged(added, removed, initState, initMetadata);
        }
      }
      if (!participants_) {
        initParticipants = gapi.hangout.getParticipants();
        if (initParticipants) {
          onParticipantsChanged(initParticipants);
        }
      }

      gapi.hangout.removeApiReadyListener(initHangout);
    };

    gapi.hangout.addApiReadyListener(initHangout);
    getToken();
  }
}());



