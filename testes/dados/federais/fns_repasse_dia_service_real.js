/**
 * @desc Define um módulo anonimo dependente de app e
 * cria o serviço repasseDiaService
 */
define([
	'app'
],
	/**
	 *
	 * @param app
	 * @returns {*}
	 */
	function (app) {

		/**
		 *
		 * @type {string}
		 * @desc var privada que referencia a URL de acesso à API repasse-dia/api/v1/
		 */
		var cGetUrl = window.location.pathname;

		/**
		 * @param Restangular, $log
		 * @constructor
		 */
		var RepasseDiaService = function (Restangular, $log) {

			this.resource = 'recursos/repasse-dia';

			this.$log = $log;
			this.Restangular = Restangular;

			this.filtroParams = {};
		}

		RepasseDiaService.prototype.consultar = function(params) {

			return this.Restangular.all(cGetUrl)
				.customGET(this.resource + '/consultar', params);
		}

		RepasseDiaService.prototype.buscarDetalheFinal = function(params) {

			return this.Restangular.all(cGetUrl)
				.customGET(this.resource + '/detalhar-pagamento-dia-final', params);
		}
		
		RepasseDiaService.prototype.buscarDetalhe = function(params) {

			return this.Restangular.all(cGetUrl)
			.customGET(this.resource + '/detalhar-pagamento-dia', params);
		}
		
		RepasseDiaService.prototype.buscarDetalhePagamento = function(params) {
			console.info("RepasseDiaService.prototype.buscarDetalhePagamento", params);
			
			return this.Restangular.all(cGetUrl).customGET(this.resource + '/detalhar-pagamento', params);
		}

		RepasseDiaService.prototype.buscarDetalhePagamentoEmenda = function(params) {
			console.info("RepasseDiaService.prototype.buscarDetalhePagamentoEmenda", params);

			return this.Restangular.all(cGetUrl).customGET(this.resource + '/detalhar-pagamento-emenda', params);
		}

		RepasseDiaService.prototype.ultimoPagamentoDia = function() {

			return this.Restangular.all(cGetUrl)
				.customGET(this.resource + '/recuperar-data-ultimo-pagamento');
		}

/*		RepasseDiaService.prototype.cGet = function (resource, params) {
			return this.Restangular.all(cGetUrl).customGET(this.resource, params);
		}*/
		
		RepasseDiaService.prototype.gerarPlanilhaDetalhada = function (params) {
			return this.Restangular.all(this.resource + '/planilha-detalhada')
			.withHttpConfig({ responseType: 'arraybuffer' })
			.post(params);
		}

		RepasseDiaService.prototype.gerarPlanilhaDetalhadaNovaEstrutura = function (params) {
			return this.Restangular.all(this.resource + '/planilha-detalhada-nova-estrutura')
			.withHttpConfig({ responseType: 'arraybuffer' })
			.post(params);
		}

		RepasseDiaService.prototype.gerarPlanilhaDetalhadaFinal = function (params) {
			return this.Restangular.all(this.resource + '/planilha-detalhada-final')
								   .withHttpConfig({ responseType: 'arraybuffer' })
								   .post(params);
		}

		/**
		 * @desc Dependency Injection
		 */
		RepasseDiaService.$inject = ['Restangular', '$log'];

		/**
		 * @desc Criação do serviço angularJS
		 * @type {boolean}
		 */
		app.service('repasseDiaService', RepasseDiaService);

		return app;
	}
);
